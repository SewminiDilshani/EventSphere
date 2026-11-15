
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Venue, User, Event, VenueHire
from app.dependencies import require_role

router = APIRouter(
    prefix="/venues",
    tags=["Venue Management"]
)

TURNAROUND_BUFFER = timedelta(hours=1)


# -----------------------------
# Request Schemas
# -----------------------------

class VenueCreate(BaseModel):
    name: str
    location: str
    capacity: int = Field(gt=0)
    description: str = ""
    image: str = ""
    hourly_rate: float = Field(ge=0)
    is_open_for_hire: bool = False


class VenueUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    capacity: int | None = Field(default=None, gt=0)
    description: str | None = None
    image: str | None = None
    hourly_rate: float | None = Field(default=None, ge=0)
    is_open_for_hire: bool | None = None


# -----------------------------
# Helper: Check Venue Availability
# -----------------------------

def check_venue_availability(
    db,
    venue_id,
    start_time,
    end_time,
    exclude_event_id=None
):
    if start_time >= end_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    event_query = db.query(Event).filter(
        Event.venue_id == venue_id,
        Event.status != "cancelled",
        Event.start_time < end_time + TURNAROUND_BUFFER,
        Event.end_time > start_time - TURNAROUND_BUFFER
    )

    if exclude_event_id is not None:
        event_query = event_query.filter(
            Event.id != exclude_event_id
        )

    if event_query.first():
        return False

    hire_query = db.query(VenueHire).filter(
        VenueHire.venue_id == venue_id,
        VenueHire.status.in_(["pending", "approved", "confirmed"]),
        VenueHire.start_time < end_time + TURNAROUND_BUFFER,
        VenueHire.end_time > start_time - TURNAROUND_BUFFER
    )

    if hire_query.first():
        return False

    return True


# -----------------------------
# Create Venue (Admin)
# -----------------------------

@router.post("/")
def create_venue(
    data: VenueCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    new_venue = Venue(**data.model_dump())

    try:
        db.add(new_venue)
        db.commit()
        db.refresh(new_venue)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not create venue"
        )

    return {
        "message": "Venue created successfully",
        "venue_id": new_venue.id,
        "name": new_venue.name
    }


# -----------------------------
# View All Venues
# -----------------------------

@router.get("/")
def get_venues(db: Session = Depends(get_db)):
    return db.query(Venue).all()


# -----------------------------
# View Venues Available for Hire
# -----------------------------

@router.get("/hire/available")
def get_hire_venues(db: Session = Depends(get_db)):
    return db.query(Venue).filter(
        Venue.is_open_for_hire == True
    ).all()


# -----------------------------
# Check Venue Availability
# -----------------------------

@router.get("/{venue_id}/availability")
def venue_availability(
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    db: Session = Depends(get_db)
):
    venue = db.query(Venue).filter(
        Venue.id == venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    available = check_venue_availability(
        db,
        venue_id,
        start_time,
        end_time
    )

    return {
        "venue_id": venue.id,
        "venue_name": venue.name,
        "available": available,
        "start_time": start_time,
        "end_time": end_time
    }


# -----------------------------
# View One Venue
# -----------------------------

@router.get("/{venue_id}")
def get_venue(
    venue_id: int,
    db: Session = Depends(get_db)
):
    venue = db.query(Venue).filter(
        Venue.id == venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    return venue


# -----------------------------
# Update Venue (Admin)
# -----------------------------

@router.put("/{venue_id}")
def update_venue(
    venue_id: int,
    data: VenueUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    venue = db.query(Venue).filter(
        Venue.id == venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    update_data = data.model_dump(exclude_unset=True)

    new_capacity = update_data.get(
        "capacity", venue.capacity
    )

    if new_capacity < 1:
        raise HTTPException(
            status_code=400,
            detail="Venue capacity must be positive"
        )

    # Do not reduce capacity below existing event ticket totals
    events = db.query(Event).filter(
        Event.venue_id == venue_id,
        Event.status != "cancelled"
    ).all()

    from app.models import TicketCategory

    for event in events:
        categories = db.query(TicketCategory).filter(
            TicketCategory.event_id == event.id
        ).all()

        total = sum(category.quantity for category in categories)

        if total > new_capacity:
            raise HTTPException(
                status_code=400,
                detail="Capacity is lower than an existing event's ticket allocation"
            )

    for key, value in update_data.items():
        setattr(venue, key, value)

    try:
        db.commit()
        db.refresh(venue)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update venue"
        )

    return {
        "message": "Venue updated successfully",
        "venue_id": venue.id,
        "name": venue.name
    }


# -----------------------------
# Delete Venue (Admin)
# -----------------------------

@router.delete("/{venue_id}")
def delete_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin"))
):
    venue = db.query(Venue).filter(
        Venue.id == venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    existing_events = db.query(Event).filter(
        Event.venue_id == venue_id
    ).first()

    existing_hires = db.query(VenueHire).filter(
        VenueHire.venue_id == venue_id
    ).first()

    if existing_events or existing_hires:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete venue with existing events or hire records"
        )

    try:
        db.delete(venue)
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not delete venue"
        )

    return {
        "message": "Venue deleted successfully",
        "venue_id": venue_id
    }
