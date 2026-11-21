
from datetime import datetime, timedelta
from io import BytesIO
import logging
import secrets

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from PIL import Image, UnidentifiedImageError
from fastapi.responses import Response
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    Event,
    EventCoverImage,
    Venue,
    VenueHire,
    TicketCategory,
    User,
    Booking,
    Ticket
)
from app.dependencies import get_optional_current_user, require_role
from app.timeutils import get_local_now, to_local_naive

router = APIRouter(
    prefix="/events",
    tags=["Event Management"]
)

TURNAROUND_BUFFER = timedelta(hours=1)
MAX_COVER_SIZE = 5 * 1024 * 1024
MAX_COVER_PIXELS = 20_000_000
COVER_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp"
}
logger = logging.getLogger(__name__)


# -----------------------------
# Request Schemas
# -----------------------------

class TicketCategoryData(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    price: float = Field(ge=0)
    quantity: int = Field(gt=0)


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    venue_id: int = Field(gt=0)
    start_time: datetime
    end_time: datetime
    ticket_categories: list[TicketCategoryData]


class EventUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    venue_id: int | None = Field(default=None, gt=0)
    start_time: datetime | None = None
    end_time: datetime | None = None


# -----------------------------
# Helper Functions
# -----------------------------

def check_event_time(start_time, end_time, require_future=False):
    if start_time >= end_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    if require_future and start_time <= get_local_now():
        raise HTTPException(
            status_code=400,
            detail="Event must start in the future"
        )


def check_venue_capacity(db, venue, ticket_categories):
    total_tickets = sum(
        ticket.quantity for ticket in ticket_categories
    )

    if total_tickets > venue.capacity:
        raise HTTPException(
            status_code=400,
            detail="Ticket quantity exceeds venue capacity"
        )

    return total_tickets


def check_venue_conflict(
    db,
    venue_id,
    start_time,
    end_time,
    exclude_event_id=None
):
    query = db.query(Event).filter(
        Event.venue_id == venue_id,
        Event.status != "cancelled",
        Event.start_time < end_time + TURNAROUND_BUFFER,
        Event.end_time > start_time - TURNAROUND_BUFFER
    )

    if exclude_event_id is not None:
        query = query.filter(Event.id != exclude_event_id)

    if query.first():
        raise HTTPException(
            status_code=400,
            detail="Venue is already booked during this time"
        )

    hire_conflict = db.query(VenueHire).filter(
        VenueHire.venue_id == venue_id,
        VenueHire.status.in_(["pending", "approved", "confirmed"]),
        VenueHire.start_time < end_time + TURNAROUND_BUFFER,
        VenueHire.end_time > start_time - TURNAROUND_BUFFER
    ).first()

    if hire_conflict:
        raise HTTPException(
            status_code=400,
            detail="Venue has a pending or confirmed hire during this time"
        )


def lock_venue(db: Session, venue_id: int):
    venue_query = db.query(Venue).filter(
        Venue.id == venue_id
    )

    if db.get_bind().dialect.name == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))
        return venue_query.first()

    return venue_query.with_for_update().first()


def event_display_data(db, event):
    venue = db.query(Venue).filter(
        Venue.id == event.venue_id
    ).first()
    starting_price = db.query(
        func.min(TicketCategory.price)
    ).filter(
        TicketCategory.event_id == event.id
    ).scalar()

    data = {
        column.name: getattr(event, column.name)
        for column in Event.__table__.columns
    }
    data.update({
        "venue_name": venue.name if venue else None,
        "venue_location": venue.location if venue else None,
        "starting_price": starting_price
    })
    return data


# -----------------------------
# Create Event (Admin)
# -----------------------------

@router.post("/")
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    venue = lock_venue(db, data.venue_id)

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    start_time = to_local_naive(data.start_time)
    end_time = to_local_naive(data.end_time)
    check_event_time(start_time, end_time, require_future=True)

    if not data.ticket_categories:
        raise HTTPException(
            status_code=400,
            detail="At least one ticket category is required"
        )

    total_tickets = check_venue_capacity(
        db, venue, data.ticket_categories
    )

    check_venue_conflict(
        db,
        data.venue_id,
        start_time,
        end_time
    )

    new_event = Event(
        title=data.title,
        category=data.category,
        description=data.description,
        venue_id=data.venue_id,
        start_time=start_time,
        end_time=end_time,
        status="draft"
    )

    try:
        db.add(new_event)
        db.flush()

        for ticket in data.ticket_categories:
            db.add(
                TicketCategory(
                    event_id=new_event.id,
                    name=ticket.name,
                    price=ticket.price,
                    quantity=ticket.quantity
                )
            )

        db.commit()
        db.refresh(new_event)

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not create event"
        )

    return {
        "message": "Event created successfully",
        "event_id": new_event.id,
        "title": new_event.title,
        "status": new_event.status,
        "total_tickets": total_tickets
    }


# -----------------------------
# View All Events
# -----------------------------

@router.get("/")
def get_events(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    events = db.query(Event).order_by(
        Event.start_time.asc()
    ).all()
    return [
        event_display_data(db, event)
        for event in events
    ]


# -----------------------------
# View Published Events
# -----------------------------

@router.get("/published")
def get_published_events(db: Session = Depends(get_db)):
    events = db.query(Event).filter(
        Event.status == "published"
    ).order_by(Event.start_time.asc()).all()
    return [
        event_display_data(db, event)
        for event in events
    ]


@router.post("/{event_id}/cover")
async def upload_event_cover(
    event_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if event.status == "cancelled":
        raise HTTPException(
            status_code=400,
            detail="Cancelled event covers cannot be changed"
        )

    image_data = await file.read(MAX_COVER_SIZE + 1)
    if len(image_data) > MAX_COVER_SIZE:
        raise HTTPException(
            status_code=413,
            detail="Cover image must be 5 MB or smaller"
        )

    try:
        with Image.open(BytesIO(image_data)) as image:
            image_format = image.format
            if image_format not in COVER_TYPES:
                raise HTTPException(
                    status_code=400,
                    detail="Upload a JPEG, PNG, or WebP image"
                )
            if image.width * image.height > MAX_COVER_PIXELS:
                raise HTTPException(
                    status_code=400,
                    detail="Cover image dimensions are too large"
                )
            image.verify()
    except HTTPException:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        SyntaxError,
        ValueError
    ):
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is not a valid image"
        )

    try:
        cover = db.query(EventCoverImage).filter(
            EventCoverImage.event_id == event.id
        ).first()
        if cover is None:
            cover = EventCoverImage(event_id=event.id)
            db.add(cover)

        cover.image_data = image_data
        cover.content_type = COVER_TYPES[image_format]
        event.cover_image_url = f"/events/{event.id}/cover"
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not save event cover image")
        raise HTTPException(
            status_code=500,
            detail="Could not save the event cover image"
        )

    return {
        "message": "Event cover uploaded successfully",
        "cover_image_url": event.cover_image_url
    }


@router.get("/{event_id}/cover")
def get_event_cover(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_optional_current_user)
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()
    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if (
        event.status != "published"
        and (current_user is None or current_user.role != "admin")
    ):
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    cover = db.query(EventCoverImage).filter(
        EventCoverImage.event_id == event_id
    ).first()
    if not cover:
        raise HTTPException(
            status_code=404,
            detail="Event cover image not found"
        )

    return Response(
        content=cover.image_data,
        media_type=cover.content_type,
        headers={"Cache-Control": "private, no-cache"}
    )


# -----------------------------
# View One Event
# -----------------------------

@router.get("/{event_id}")
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_optional_current_user)
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if (
        event.status != "published"
        and (current_user is None or current_user.role != "admin")
    ):
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return event_display_data(db, event)


# -----------------------------
# Update Draft Event (Admin)
# -----------------------------

@router.put("/{event_id}")
def update_event(
    event_id: int,
    data: EventUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if event.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Only draft events can be updated"
        )

    update_data = data.model_dump(exclude_unset=True)

    if "start_time" in update_data:
        update_data["start_time"] = to_local_naive(
            update_data["start_time"]
        )

    if "end_time" in update_data:
        update_data["end_time"] = to_local_naive(
            update_data["end_time"]
        )

    new_venue_id = update_data.get("venue_id", event.venue_id)
    new_start = to_local_naive(
        update_data.get("start_time", event.start_time)
    )
    new_end = to_local_naive(
        update_data.get("end_time", event.end_time)
    )

    venue = lock_venue(db, new_venue_id)

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    check_event_time(
        new_start,
        new_end,
        require_future=(
            "start_time" in update_data or "end_time" in update_data
        )
    )

    check_venue_conflict(
        db,
        new_venue_id,
        new_start,
        new_end,
        exclude_event_id=event.id
    )

    current_tickets = db.query(TicketCategory).filter(
        TicketCategory.event_id == event.id
    ).all()

    total_tickets = sum(
        ticket.quantity for ticket in current_tickets
    )

    if total_tickets > venue.capacity:
        raise HTTPException(
            status_code=400,
            detail="Ticket quantity exceeds new venue capacity"
        )

    for field, value in update_data.items():
        setattr(event, field, value)

    try:
        db.commit()
        db.refresh(event)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update event"
        )

    return {
        "message": "Event updated successfully",
        "event_id": event.id,
        "status": event.status
    }


# -----------------------------
# Publish Event (Admin)
# -----------------------------

@router.put("/{event_id}/publish")
def publish_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if event.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Only draft events can be published"
        )

    venue = lock_venue(db, event.venue_id)

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    event.start_time = to_local_naive(event.start_time)
    event.end_time = to_local_naive(event.end_time)
    check_event_time(
        event.start_time,
        event.end_time,
        require_future=True
    )

    categories = db.query(TicketCategory).filter(
        TicketCategory.event_id == event.id
    ).all()

    if not categories:
        raise HTTPException(
            status_code=400,
            detail="Event must have at least one ticket category"
        )

    check_venue_capacity(db, venue, categories)

    check_venue_conflict(
        db,
        event.venue_id,
        event.start_time,
        event.end_time,
        exclude_event_id=event.id
    )

    event.status = "published"
    db.commit()

    return {
        "message": "Event published successfully",
        "event_id": event.id,
        "status": event.status
    }


# -----------------------------
# Cancel Event (Admin)
# -----------------------------

@router.put("/{event_id}/cancel")
def cancel_event(
    event_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    try:
        sqlite_session = db.get_bind().dialect.name == "sqlite"
        if sqlite_session:
            db.execute(text("BEGIN IMMEDIATE"))

        event_query = db.query(Event).filter(
            Event.id == event_id
        )
        if not sqlite_session:
            event_query = event_query.with_for_update()

        event = event_query.first()
        if not event:
            raise HTTPException(
                status_code=404,
                detail="Event not found"
            )

        if event.status == "cancelled":
            raise HTTPException(
                status_code=400,
                detail="Event is already cancelled"
            )

        bookings_query = db.query(Booking).filter(
            Booking.event_id == event.id,
            Booking.status == "confirmed"
        )
        if not sqlite_session:
            bookings_query = bookings_query.with_for_update()

        bookings = bookings_query.all()
        for booking in bookings:
            booking.status = "cancelled"
            booking.refund_amount = round(
                float(booking.total_amount),
                2
            )
            booking.refund_reference = (
                "SIM-REF-" + secrets.token_hex(12)
            )

            tickets = db.query(Ticket).filter(
                Ticket.booking_id == booking.id
            ).all()
            for ticket in tickets:
                ticket.status = "cancelled"

        event.status = "cancelled"
        db.commit()
        return {
            "message": "Event cancelled successfully",
            "event_id": event.id,
            "status": event.status,
            "refunded_bookings": len(bookings),
            "refund_amount": round(
                sum(float(booking.total_amount) for booking in bookings),
                2
            ),
            "payment_note": "Full simulated refunds issued; no real payment was processed."
        }
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not cancel event")
        raise HTTPException(
            status_code=503,
            detail="Could not cancel event. Please try again."
        )
    except Exception:
        db.rollback()
        logger.exception("Unexpected error cancelling event")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while cancelling event"
        )
