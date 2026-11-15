
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models import Venue, VenueHire, Event

router = APIRouter(
    prefix="/venue-hires",
    tags=["Private Venue Hire"]
)

TURNAROUND_BUFFER = timedelta(hours=1)


# -----------------------------
# Request Schema
# -----------------------------

class VenueHireCreate(BaseModel):
    venue_id: int
    purpose: str
    guest_count: int = Field(gt=0)
    start_time: datetime
    end_time: datetime


# -----------------------------
# Helper: Check Availability
# -----------------------------

def is_venue_available(
    db,
    venue_id,
    start_time,
    end_time,
    exclude_hire_id=None
):
    event_conflict = db.query(Event).filter(
        Event.venue_id == venue_id,
        Event.status != "cancelled",
        Event.start_time < end_time + TURNAROUND_BUFFER,
        Event.end_time > start_time - TURNAROUND_BUFFER
    ).first()

    if event_conflict:
        return False

    hire_query = db.query(VenueHire).filter(
        VenueHire.venue_id == venue_id,
        VenueHire.status.in_(
            ["pending", "approved", "confirmed"]
        ),
        VenueHire.start_time < end_time + TURNAROUND_BUFFER,
        VenueHire.end_time > start_time - TURNAROUND_BUFFER
    )

    if exclude_hire_id is not None:
        hire_query = hire_query.filter(
            VenueHire.id != exclude_hire_id
        )

    return hire_query.first() is None


# -----------------------------
# Helper: Find Alternative Venues
# -----------------------------

def find_alternative_venues(
    db,
    requested_venue_id,
    guest_count,
    start_time,
    end_time
):
    venues = db.query(Venue).filter(
        Venue.is_open_for_hire == True,
        Venue.capacity >= guest_count,
        Venue.id != requested_venue_id
    ).all()

    alternatives = []

    for venue in venues:
        if is_venue_available(
            db,
            venue.id,
            start_time,
            end_time
        ):
            hours = (
                end_time - start_time
            ).total_seconds() / 3600

            alternatives.append({
                "venue_id": venue.id,
                "venue_name": venue.name,
                "location": venue.location,
                "capacity": venue.capacity,
                "hourly_rate": venue.hourly_rate,
                "estimated_price": round(
                    hours * venue.hourly_rate, 2
                )
            })

    return alternatives


# -----------------------------
# Request Private Venue Hire
# Attendee Only
# -----------------------------

@router.post("/")
def request_venue_hire(
    data: VenueHireCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):
    venue = db.query(Venue).filter(
        Venue.id == data.venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    if not venue.is_open_for_hire:
        raise HTTPException(
            status_code=400,
            detail="Venue is not open for hire"
        )

    if data.start_time >= data.end_time:
        raise HTTPException(
            status_code=400,
            detail="End time must be after start time"
        )

    if data.start_time <= datetime.now():
        raise HTTPException(
            status_code=400,
            detail="Choose a future date and time"
        )

    if data.guest_count > venue.capacity:
        raise HTTPException(
            status_code=400,
            detail="Guest count exceeds venue capacity"
        )

    # Check requested venue availability
    available = is_venue_available(
        db,
        venue.id,
        data.start_time,
        data.end_time
    )

    # If unavailable, suggest alternatives
    if not available:
        alternatives = find_alternative_venues(
            db,
            venue.id,
            data.guest_count,
            data.start_time,
            data.end_time
        )

        return {
            "status": "unavailable",
            "message": "Requested venue is unavailable",
            "alternatives": alternatives
        }

    # Calculate hire price
    hours = (
        data.end_time - data.start_time
    ).total_seconds() / 3600

    total_price = round(
        hours * venue.hourly_rate, 2
    )

    # Create pending request.
    # Admin must approve before final confirmation.
    hire = VenueHire(
        user_id=current_user.id,
        venue_id=venue.id,
        purpose=data.purpose,
        guest_count=data.guest_count,
        start_time=data.start_time,
        end_time=data.end_time,
        total_price=total_price,
        status="pending"
    )

    try:
        db.add(hire)
        db.commit()
        db.refresh(hire)

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not submit venue hire request"
        )

    return {
        "message": "Venue hire request submitted",
        "hire_id": hire.id,
        "venue": venue.name,
        "purpose": hire.purpose,
        "guest_count": hire.guest_count,
        "total_price": total_price,
        "status": hire.status,
        "message_for_user": "Waiting for admin approval"
    }


# -----------------------------
# View My Hire Requests
# Attendee Only
# -----------------------------

@router.get("/my-requests")
def my_venue_requests(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):
    hires = db.query(VenueHire).filter(
        VenueHire.user_id == current_user.id
    ).order_by(VenueHire.id.desc()).all()

    return [
        {
            "hire_id": hire.id,
            "venue_id": hire.venue_id,
            "purpose": hire.purpose,
            "guest_count": hire.guest_count,
            "start_time": hire.start_time,
            "end_time": hire.end_time,
            "total_price": hire.total_price,
            "status": hire.status
        }
        for hire in hires
    ]


# -----------------------------
# View All Hire Requests
# Admin Only
# -----------------------------

@router.get("/admin/all")
def all_venue_requests(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    hires = db.query(VenueHire).order_by(
        VenueHire.id.desc()
    ).all()

    return [
        {
            "hire_id": hire.id,
            "user_id": hire.user_id,
            "venue_id": hire.venue_id,
            "purpose": hire.purpose,
            "guest_count": hire.guest_count,
            "start_time": hire.start_time,
            "end_time": hire.end_time,
            "total_price": hire.total_price,
            "status": hire.status
        }
        for hire in hires
    ]


# -----------------------------
# Admin Approve / Reject
# -----------------------------

@router.put("/admin/{hire_id}/decision")
def decide_venue_request(
    hire_id: int,
    decision: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    hire = db.query(VenueHire).filter(
        VenueHire.id == hire_id
    ).first()

    if not hire:
        raise HTTPException(
            status_code=404,
            detail="Request not found"
        )

    if hire.status != "pending":
        raise HTTPException(
            status_code=400,
            detail="Only pending requests can be reviewed"
        )

    if decision not in ["confirmed", "rejected"]:
        raise HTTPException(
            status_code=400,
            detail="Decision must be confirmed or rejected"
        )

    if decision == "confirmed":
        venue = db.query(Venue).filter(
            Venue.id == hire.venue_id
        ).first()

        if not venue or not venue.is_open_for_hire:
            raise HTTPException(
                status_code=400,
                detail="Venue is not available for hire"
            )

        # Recheck availability before approval
        available = is_venue_available(
            db,
            hire.venue_id,
            hire.start_time,
            hire.end_time,
            exclude_hire_id=hire.id
        )

        if not available:
            alternatives = find_alternative_venues(
                db,
                hire.venue_id,
                hire.guest_count,
                hire.start_time,
                hire.end_time
            )

            return {
                "status": "unavailable",
                "message": "Venue is no longer available",
                "alternatives": alternatives
            }

    hire.status = decision

    try:
        db.commit()
        db.refresh(hire)
    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update venue request"
        )

    return {
        "message": "Venue request updated",
        "hire_id": hire.id,
        "status": hire.status
    }
