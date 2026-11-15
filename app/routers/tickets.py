
import io
import base64

import qrcode

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Ticket, Booking, Event
from app.dependencies import require_role


router = APIRouter(
    prefix="/tickets",
    tags=["Digital Tickets"]
)


class ManualTicketScan(BaseModel):
    ticket_code: str
    event_id: int | None = None


# --------------------------------
# Get Attendee Digital Tickets
# --------------------------------

@router.get("/my-tickets")
def my_tickets(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee"))
):
    bookings = db.query(Booking).filter(
        Booking.user_id == current_user.id
    ).all()

    result = []

    for booking in bookings:

        tickets = db.query(Ticket).filter(
            Ticket.booking_id == booking.id
        ).all()

        event = db.query(Event).filter(
            Event.id == booking.event_id
        ).first()

        booking_status = getattr(
            booking, "status", "confirmed"
        )

        for ticket in tickets:

            qr_base64 = None

            if (
                ticket.status == "valid"
                and booking_status == "confirmed"
                and not getattr(ticket, "checked_in", False)
            ):
                qr = qrcode.make(ticket.ticket_code)

                buffer = io.BytesIO()
                qr.save(buffer, format="PNG")

                qr_base64 = base64.b64encode(
                    buffer.getvalue()
                ).decode("utf-8")

            result.append({
                "ticket_id": ticket.id,
                "booking_id": booking.id,
                "event_id": booking.event_id,
                "event": event.title if event else "Unknown",
                "ticket_code": ticket.ticket_code,
                "status": ticket.status,
                "booking_status": booking_status,
                "checked_in": getattr(
                    ticket, "checked_in", False
                ),
                "checked_in_at": getattr(
                    ticket, "checked_in_at", None
                ),
                "qr_code": (
                    "data:image/png;base64," + qr_base64
                    if qr_base64 else None
                )
            })

    return result


# --------------------------------
# Common Ticket Validation
# --------------------------------

def process_ticket_scan(
    ticket_code,
    db,
    expected_event_id=None
):

    ticket = db.query(Ticket).filter(
        Ticket.ticket_code == ticket_code
    ).first()

    if not ticket:
        raise HTTPException(
            status_code=404,
            detail="Invalid ticket. Ticket not found."
        )

    if ticket.status != "valid":
        raise HTTPException(
            status_code=400,
            detail="Ticket rejected. This ticket has been cancelled."
        )

    booking = db.query(Booking).filter(
        Booking.id == ticket.booking_id
    ).first()

    if not booking:
        raise HTTPException(
            status_code=400,
            detail="Ticket rejected. Booking not found."
        )

    if booking.status != "confirmed":
        raise HTTPException(
            status_code=400,
            detail="Ticket rejected. Booking is not confirmed."
        )

    event = db.query(Event).filter(
        Event.id == booking.event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Ticket rejected. Event not found."
        )

    if (
        expected_event_id is not None
        and booking.event_id != expected_event_id
    ):
        raise HTTPException(
            status_code=400,
            detail="Ticket rejected. This ticket belongs to a different event."
        )

    if getattr(ticket, "checked_in", False):
        raise HTTPException(
            status_code=400,
            detail="Ticket rejected. This ticket has already been used."
        )

    # Atomic update prevents two simultaneous scans
    # from admitting the same ticket.

    try:

        updated_rows = db.query(Ticket).filter(
            Ticket.id == ticket.id,
            Ticket.status == "valid",
            Ticket.checked_in == False
        ).update(
            {
                "checked_in": True,
                "checked_in_at": datetime.now()
            },
            synchronize_session=False
        )

        if updated_rows == 0:

            db.rollback()

            db.refresh(ticket)

            if ticket.status != "valid":
                raise HTTPException(
                    status_code=400,
                    detail="Ticket rejected. This ticket has been cancelled."
                )

            if ticket.checked_in:
                raise HTTPException(
                    status_code=400,
                    detail="Ticket rejected. This ticket has already been used."
                )

            raise HTTPException(
                status_code=400,
                detail="Ticket could not be checked in."
            )

        db.commit()

        return {
            "message": "Check-in successful",
            "ticket_id": ticket.id,
            "booking_id": booking.id,
            "event_id": event.id,
            "event": event.title,
            "checked_in": True,
            "checked_in_at": datetime.now()
        }

    except HTTPException:
        raise

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Ticket scanning failed. Please try again."
        )


# --------------------------------
# QR Code Scan - Staff Only
# --------------------------------

@router.post("/scan/{ticket_code}")
def scan_ticket(
    ticket_code: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("staff")),
    event_id: int | None = None
):
    return process_ticket_scan(
        ticket_code,
        db,
        expected_event_id=event_id
    )


# --------------------------------
# Manual Ticket Entry - Staff Only
# --------------------------------

@router.post("/scan")
def manual_scan_ticket(
    data: ManualTicketScan,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("staff"))
):
    return process_ticket_scan(
        data.ticket_code,
        db,
        expected_event_id=data.event_id
    )


# --------------------------------
# Admin: View All Tickets
# --------------------------------

@router.get("/admin/all")
def get_all_tickets(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    tickets = db.query(Ticket).order_by(
        Ticket.id.desc()
    ).all()

    result = []

    for ticket in tickets:

        booking = db.query(Booking).filter(
            Booking.id == ticket.booking_id
        ).first()

        if not booking:
            continue

        event = db.query(Event).filter(
            Event.id == booking.event_id
        ).first()

        result.append({
            "ticket_id": ticket.id,
            "booking_id": booking.id,
            "user_id": booking.user_id,
            "event_id": booking.event_id,
            "event": event.title if event else "Unknown",
            "ticket_code": ticket.ticket_code,
            "status": ticket.status,
            "checked_in": getattr(
                ticket, "checked_in", False
            ),
            "checked_in_at": getattr(
                ticket, "checked_in_at", None
            )
        })

    return result
