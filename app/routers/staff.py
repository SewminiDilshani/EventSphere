
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_role
from app.models import User, Event, Venue, Ticket, Booking


router = APIRouter(
    prefix="/staff",
    tags=["Staff"]
)


# -----------------------------
# Staff Dashboard
# -----------------------------

@router.get("/dashboard")
def staff_dashboard(
    user: User = Depends(require_role("staff"))
):
    return {
        "message": "Welcome to Staff Dashboard",
        "user": user.name,
        "role": user.role
    }


# -----------------------------
# View Published Events
# -----------------------------

@router.get("/events")
def staff_events(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("staff"))
):
    events = db.query(Event).filter(
        Event.status == "published"
    ).order_by(
        Event.start_time.asc()
    ).all()

    result = []

    for event in events:

        venue = db.query(Venue).filter(
            Venue.id == event.venue_id
        ).first()

        result.append({
            "event_id": event.id,
            "title": event.title,
            "category": event.category,
            "venue_id": event.venue_id,
            "venue_name": venue.name if venue else "Unknown Venue",
            "start_time": event.start_time,
            "end_time": event.end_time,
            "status": event.status
        })

    return result


# -----------------------------
# Event Check-in Statistics
# -----------------------------

@router.get("/events/{event_id}/check-in-summary")
def event_checkin_summary(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("staff"))
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    total_tickets = db.query(Ticket).join(
        Booking,
        Ticket.booking_id == Booking.id
    ).filter(
        Booking.event_id == event_id,
        Booking.status == "confirmed",
        Ticket.status == "valid"
    ).count()

    checked_in = db.query(Ticket).join(
        Booking,
        Ticket.booking_id == Booking.id
    ).filter(
        Booking.event_id == event_id,
        Booking.status == "confirmed",
        Ticket.status == "valid",
        Ticket.checked_in == True
    ).count()

    return {
        "event_id": event.id,
        "event_name": event.title,
        "total_valid_tickets": total_tickets,
        "checked_in": checked_in,
        "not_checked_in": total_tickets - checked_in
    }


# -----------------------------
# View Event Check-in List
# -----------------------------

@router.get("/events/{event_id}/check-ins")
def event_checkin_list(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("staff"))
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    tickets = db.query(Ticket).join(
        Booking,
        Ticket.booking_id == Booking.id
    ).filter(
        Booking.event_id == event_id,
        Booking.status == "confirmed"
    ).order_by(
        Ticket.id.desc()
    ).all()

    result = []

    for ticket in tickets:
        result.append({
            "ticket_id": ticket.id,
            "ticket_code": ticket.ticket_code,
            "ticket_status": ticket.status,
            "checked_in": ticket.checked_in,
            "checked_in_at": ticket.checked_in_at
        })

    return {
        "event_id": event.id,
        "event_name": event.title,
        "tickets": result
    }


# -----------------------------
# Staff Dashboard Summary
# -----------------------------

@router.get("/summary")
def staff_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("staff"))
):
    published_events = db.query(Event).filter(
        Event.status == "published"
    ).count()

    total_checkins = db.query(Ticket).join(
        Booking,
        Ticket.booking_id == Booking.id
    ).filter(
        Booking.status == "confirmed",
        Ticket.status == "valid",
        Ticket.checked_in == True
    ).count()

    return {
        "staff_name": current_user.name,
        "published_events": published_events,
        "total_check_ins": total_checkins
    }
