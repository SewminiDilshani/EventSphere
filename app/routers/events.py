
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Event, Venue, TicketCategory, User
from app.dependencies import require_role

router = APIRouter(
    prefix="/events",
    tags=["Event Management"]
)

TURNAROUND_BUFFER = timedelta(hours=1)


# -----------------------------
# Request Schemas
# -----------------------------

class TicketCategoryData(BaseModel):
    name: str
    price: float = Field(ge=0)
    quantity: int = Field(gt=0)


class EventCreate(BaseModel):
    title: str
    category: str
    description: str = ""
    venue_id: int
    start_time: datetime
    end_time: datetime
    ticket_categories: list[TicketCategoryData]


class EventUpdate(BaseModel):
    title: str | None = None
    category: str | None = None
    description: str | None = None
    venue_id: int | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None


# -----------------------------
# Helper Functions
# -----------------------------

def check_event_time(start_time, end_time):
    if start_time >= end_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
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


# -----------------------------
# Create Event (Admin)
# -----------------------------

@router.post("/")
def create_event(
    data: EventCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    venue = db.query(Venue).filter(
        Venue.id == data.venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    check_event_time(data.start_time, data.end_time)

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
        data.start_time,
        data.end_time
    )

    new_event = Event(
        title=data.title,
        category=data.category,
        description=data.description,
        venue_id=data.venue_id,
        start_time=data.start_time,
        end_time=data.end_time,
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
def get_events(db: Session = Depends(get_db)):
    return db.query(Event).all()


# -----------------------------
# View Published Events
# -----------------------------

@router.get("/published")
def get_published_events(db: Session = Depends(get_db)):
    return db.query(Event).filter(
        Event.status == "published"
    ).all()


# -----------------------------
# View One Event
# -----------------------------

@router.get("/{event_id}")
def get_event(
    event_id: int,
    db: Session = Depends(get_db)
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    return event


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

    new_venue_id = update_data.get("venue_id", event.venue_id)
    new_start = update_data.get("start_time", event.start_time)
    new_end = update_data.get("end_time", event.end_time)

    venue = db.query(Venue).filter(
        Venue.id == new_venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    check_event_time(new_start, new_end)

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

    venue = db.query(Venue).filter(
        Venue.id == event.venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    check_event_time(event.start_time, event.end_time)

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
            detail="Event is already cancelled"
        )

    event.status = "cancelled"

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not cancel event"
        )

    return {
        "message": "Event cancelled successfully",
        "event_id": event.id,
        "status": event.status
    }
