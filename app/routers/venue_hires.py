
import logging
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.dependencies import require_role
from app.models import Venue, VenueHire, Event
from app.timeutils import get_local_now, to_local_naive


router = APIRouter(
    prefix="/venue-hires",
    tags=["Private Venue Hire"]
)

logger = logging.getLogger(__name__)

TURNAROUND_BUFFER = timedelta(hours=1)


# --------------------------------
# Request Schema
# --------------------------------

class VenueHireCreate(BaseModel):
    venue_id: int
    purpose: str = Field(min_length=3, max_length=255)
    guest_count: int = Field(gt=0)
    start_time: datetime
    end_time: datetime


# --------------------------------
# Lock Venue for Concurrent Requests
# --------------------------------

def lock_venue(db: Session, venue_id: int):

    dialect = db.get_bind().dialect.name

    if dialect == "sqlite":
        db.execute(text("BEGIN IMMEDIATE"))

        return db.query(Venue).filter(
            Venue.id == venue_id
        ).first()

    return db.query(Venue).filter(
        Venue.id == venue_id
    ).with_for_update().first()


# --------------------------------
# Check Venue Availability
# --------------------------------

def is_venue_available(
    db: Session,
    venue_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_hire_id=None
):

    buffered_start = start_time - TURNAROUND_BUFFER
    buffered_end = end_time + TURNAROUND_BUFFER

    # Check existing events

    event_conflict = db.query(Event).filter(
        Event.venue_id == venue_id,
        Event.status != "cancelled",
        Event.start_time < buffered_end,
        Event.end_time > buffered_start
    ).first()

    if event_conflict:
        return False

    # Check existing venue hire requests

    hire_query = db.query(VenueHire).filter(
        VenueHire.venue_id == venue_id,
        VenueHire.status.in_(
            ["pending", "approved", "confirmed"]
        ),
        VenueHire.start_time < buffered_end,
        VenueHire.end_time > buffered_start
    )

    if exclude_hire_id is not None:
        hire_query = hire_query.filter(
            VenueHire.id != exclude_hire_id
        )

    return hire_query.first() is None


# --------------------------------
# Find Alternative Venues
# --------------------------------

def find_alternative_venues(
    db: Session,
    requested_venue_id: int,
    guest_count: int,
    start_time: datetime,
    end_time: datetime
):

    venues = db.query(Venue).filter(
        Venue.is_open_for_hire == True,
        Venue.capacity >= guest_count,
        Venue.id != requested_venue_id
    ).all()

    hours = (
        end_time - start_time
    ).total_seconds() / 3600

    alternatives = []

    for venue in venues:

        available = is_venue_available(
            db,
            venue.id,
            start_time,
            end_time
        )

        if available:

            estimated_price = round(
                float(venue.hourly_rate) * hours,
                2
            )

            alternatives.append({
                "venue_id": venue.id,
                "venue_name": venue.name,
                "location": venue.location,
                "capacity": venue.capacity,
                "hourly_rate": venue.hourly_rate,
                "estimated_price": estimated_price
            })

    return alternatives


# --------------------------------
# Request Private Venue Hire
# Attendee Only
# --------------------------------

@router.post("/")
def request_venue_hire(
    data: VenueHireCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):

    try:

        start_time = to_local_naive(data.start_time)
        end_time = to_local_naive(data.end_time)

        now = get_local_now()

        # Validate date and time

        if start_time >= end_time:
            raise HTTPException(
                status_code=400,
                detail="End time must be after start time"
            )

        if start_time <= now:
            raise HTTPException(
                status_code=400,
                detail="Choose a future date and time"
            )

        # Lock venue

        venue = lock_venue(
            db,
            data.venue_id
        )

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

        if data.guest_count > venue.capacity:
            raise HTTPException(
                status_code=400,
                detail="Guest count exceeds venue capacity"
            )

        # Check availability

        available = is_venue_available(
            db,
            venue.id,
            start_time,
            end_time
        )

        if not available:

            alternatives = find_alternative_venues(
                db,
                venue.id,
                data.guest_count,
                start_time,
                end_time
            )

            db.rollback()

            return {
                "status": "unavailable",
                "message": "Requested venue is unavailable",
                "alternatives": alternatives
            }

        # Calculate price

        hours = (
            end_time - start_time
        ).total_seconds() / 3600

        total_price = round(
            float(venue.hourly_rate) * hours,
            2
        )

        # Available requests that pass all checks are confirmed immediately.

        hire = VenueHire(
            user_id=current_user.id,
            venue_id=venue.id,
            purpose=data.purpose,
            guest_count=data.guest_count,
            start_time=start_time,
            end_time=end_time,
            total_price=total_price,
            status="confirmed"
        )

        db.add(hire)
        db.commit()
        db.refresh(hire)

        return {
            "message": "Venue hire request confirmed successfully.",
            "hire_id": hire.id,
            "venue": venue.name,
            "purpose": hire.purpose,
            "guest_count": hire.guest_count,
            "start_time": hire.start_time,
            "end_time": hire.end_time,
            "total_price": total_price,
            "status": hire.status,
            "payment_note": "Simulated payment only"
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Venue hire database error")

        raise HTTPException(
            status_code=503,
            detail="Could not process venue hire. Please try again."
        )

    except Exception:
        db.rollback()
        logger.exception("Venue hire unexpected error")

        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred"
        )


# --------------------------------
# View My Hire Requests
# Attendee Only
# --------------------------------

@router.get("/my-requests")
def my_venue_requests(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):

    hires = db.query(VenueHire).filter(
        VenueHire.user_id == current_user.id
    ).order_by(
        VenueHire.id.desc()
    ).all()

    return [
        {
            "id": hire.id,
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


# --------------------------------
# Admin: View All Hire Requests
# --------------------------------

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
            "id": hire.id,
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


# --------------------------------
# Admin: Approve / Reject Pending Request
# --------------------------------

@router.put("/admin/{hire_id}/decision")
def decide_venue_request(
    hire_id: int,
    decision: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    try:

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

            venue = lock_venue(
                db,
                hire.venue_id
            )

            if not venue or not venue.is_open_for_hire:
                raise HTTPException(
                    status_code=400,
                    detail="Venue is not available for hire"
                )

            if hire.guest_count > venue.capacity:
                raise HTTPException(
                    status_code=400,
                    detail="Guest count exceeds venue capacity"
                )

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

                db.rollback()

                return {
                    "status": "unavailable",
                    "message": "Venue is no longer available",
                    "alternatives": alternatives
                }

        hire.status = decision

        db.commit()
        db.refresh(hire)

        return {
            "message": "Venue request updated successfully",
            "hire_id": hire.id,
            "status": hire.status
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()
        logger.exception("Venue hire decision database error")

        raise HTTPException(
            status_code=503,
            detail="Could not update venue request"
        )

    except Exception:
        db.rollback()
        logger.exception("Venue hire decision unexpected error")

        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred"
        )
