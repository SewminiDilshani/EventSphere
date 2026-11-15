
from datetime import datetime
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import get_db
from app.dependencies import require_role
from app.models import Event, TicketCategory, Booking, Ticket


router = APIRouter(
    prefix="/bookings",
    tags=["Bookings"]
)


class BookingCreate(BaseModel):
    event_id: int
    ticket_category_id: int
    quantity: int = Field(gt=0, le=10)


# --------------------------------
# Create Booking - Attendee Only
# --------------------------------

@router.post("/")
def create_booking(
    data: BookingCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):
    try:
        db.execute(text("BEGIN IMMEDIATE"))

        event = db.query(Event).filter(
            Event.id == data.event_id
        ).first()

        if not event:
            raise HTTPException(
                status_code=404,
                detail="Event not found"
            )

        if event.status != "published":
            raise HTTPException(
                status_code=400,
                detail="Event is not available"
            )

        category = db.query(TicketCategory).filter(
            TicketCategory.id == data.ticket_category_id,
            TicketCategory.event_id == data.event_id
        ).first()

        if not category:
            raise HTTPException(
                status_code=404,
                detail="Ticket category not found"
            )

        booked_count = db.query(
            func.count(Ticket.id)
        ).join(
            Booking,
            Ticket.booking_id == Booking.id
        ).filter(
            Ticket.ticket_category_id == category.id,
            Booking.status == "confirmed",
            Ticket.status == "valid"
        ).scalar() or 0

        available = category.quantity - booked_count

        if data.quantity > available:
            raise HTTPException(
                status_code=400,
                detail=f"Only {available} tickets are available"
            )

        total = category.price * data.quantity

        booking = Booking(
            user_id=current_user.id,
            event_id=event.id,
            quantity=data.quantity,
            total_amount=total,
            payment_reference="SIM-" + secrets.token_hex(12),
            status="confirmed",
            created_at=datetime.now()
        )

        db.add(booking)
        db.flush()

        ticket_codes = []

        for _ in range(data.quantity):
            code = secrets.token_urlsafe(32)

            ticket = Ticket(
                booking_id=booking.id,
                ticket_category_id=category.id,
                ticket_code=code,
                status="valid",
                checked_in=False
            )

            db.add(ticket)
            ticket_codes.append(code)

        db.commit()
        db.refresh(booking)

        return {
            "message": "Booking successful",
            "booking_id": booking.id,
            "event": event.title,
            "ticket_category": category.name,
            "quantity": data.quantity,
            "total_amount": total,
            "payment_reference": booking.payment_reference,
            "status": booking.status,
            "tickets": ticket_codes
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Booking could not be completed. Please try again."
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while creating booking"
        )


# --------------------------------
# Attendee Booking History
# --------------------------------

@router.get("/my-bookings")
def my_bookings(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):
    bookings = db.query(Booking).filter(
        Booking.user_id == current_user.id
    ).all()

    result = []

    for booking in bookings:
        event = db.query(Event).filter(
            Event.id == booking.event_id
        ).first()

        result.append({
            "booking_id": booking.id,
            "event": event.title if event else "Unknown",
            "quantity": booking.quantity,
            "total_amount": booking.total_amount,
            "payment_reference": booking.payment_reference,
            "status": booking.status,
            "created_at": booking.created_at
        })

    return result


# --------------------------------
# Cancel Booking - Attendee Only
# --------------------------------

@router.put("/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):
    try:
        db.execute(text("BEGIN IMMEDIATE"))

        booking = db.query(Booking).filter(
            Booking.id == booking_id,
            Booking.user_id == current_user.id
        ).first()

        if not booking:
            raise HTTPException(
                status_code=404,
                detail="Booking not found"
            )

        if booking.status != "confirmed":
            raise HTTPException(
                status_code=400,
                detail="Booking cannot be cancelled"
            )

        tickets = db.query(Ticket).filter(
            Ticket.booking_id == booking.id
        ).all()

        # Do not cancel a booking after admission.
        if any(
            getattr(ticket, "checked_in", False)
            for ticket in tickets
        ):
            raise HTTPException(
                status_code=400,
                detail="Booking cannot be cancelled after check-in"
            )

        booking.status = "cancelled"

        for ticket in tickets:
            ticket.status = "cancelled"

        db.commit()

        return {
            "message": "Booking cancelled successfully",
            "booking_id": booking.id,
            "status": "cancelled",
            "refund": (
                "Simulated refund only. "
                "No real payment was processed."
            )
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(
            status_code=503,
            detail="Could not cancel booking. Please try again."
        )

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while cancelling booking"
        )


# --------------------------------
# Admin: View All Bookings
# --------------------------------

@router.get("/admin/all")
def all_bookings(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    bookings = db.query(Booking).order_by(
        Booking.created_at.desc()
    ).all()

    result = []

    for booking in bookings:
        event = db.query(Event).filter(
            Event.id == booking.event_id
        ).first()

        result.append({
            "booking_id": booking.id,
            "user_id": booking.user_id,
            "event_id": booking.event_id,
            "event": event.title if event else "Unknown",
            "quantity": booking.quantity,
            "total_amount": booking.total_amount,
            "payment_reference": booking.payment_reference,
            "status": booking.status,
            "created_at": booking.created_at
        })

    return result
