
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.dependencies import require_role

from app.models import (
    Booking,
    Event,
    Ticket,
    AgentMessage,
    Venue,
    TicketCategory,
    VenueHire
)


router = APIRouter(
    prefix="/dashboard",
    tags=["Admin Dashboard"]
)


# -----------------------------
# 1. Dashboard Summary
# -----------------------------

@router.get("/summary")
def dashboard_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    total_events = db.query(Event).count()

    published_events = db.query(Event).filter(
        Event.status == "published"
    ).count()

    total_bookings = db.query(Booking).filter(
        Booking.status == "confirmed"
    ).count()

    cancelled_bookings = db.query(Booking).filter(
        Booking.status == "cancelled"
    ).count()

    total_revenue = db.query(
        func.sum(Booking.total_amount)
    ).filter(
        Booking.status == "confirmed"
    ).scalar() or 0

    total_refunds = db.query(
        func.sum(Booking.refund_amount)
    ).scalar() or 0

    total_tickets = db.query(Ticket).filter(
        Ticket.status == "valid"
    ).count()

    checked_in = db.query(Ticket).filter(
        Ticket.status == "valid",
        Ticket.checked_in == True
    ).count()

    not_checked_in = total_tickets - checked_in

    total_agent_messages = db.query(
        AgentMessage
    ).count()

    return {
        "total_events": total_events,
        "published_events": published_events,
        "total_bookings": total_bookings,
        "cancelled_bookings": cancelled_bookings,
        "total_revenue": total_revenue,
        "total_refunds": total_refunds,
        "total_tickets": total_tickets,
        "checked_in_tickets": checked_in,
        "not_checked_in": not_checked_in,
        "agent_messages": total_agent_messages
    }


# -----------------------------
# 2. Event-wise Sales Report
# -----------------------------

@router.get("/event-sales")
def event_sales_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    events = db.query(Event).all()

    result = []

    for event in events:

        bookings = db.query(Booking).filter(
            Booking.event_id == event.id,
            Booking.status == "confirmed"
        ).all()

        revenue = sum(
            booking.total_amount
            for booking in bookings
        )

        ticket_count = sum(
            booking.quantity
            for booking in bookings
        )

        checked_in = db.query(Ticket).join(
            Booking,
            Ticket.booking_id == Booking.id
        ).filter(
            Booking.event_id == event.id,
            Booking.status == "confirmed",
            Ticket.status == "valid",
            Ticket.checked_in == True
        ).count()

        result.append({
            "event_id": event.id,
            "event_name": event.title,
            "status": event.status,
            "total_bookings": len(bookings),
            "tickets_sold": ticket_count,
            "checked_in": checked_in,
            "revenue": revenue
        })

    return result


# -----------------------------
# 3. Venue Capacity Report
# -----------------------------

@router.get("/venue-capacity")
def venue_capacity_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    venues = db.query(Venue).all()

    result = []

    for venue in venues:

        events = db.query(Event).filter(
            Event.venue_id == venue.id,
            Event.status != "cancelled"
        ).all()

        allocated = 0
        sold = 0

        for event in events:

            categories = db.query(TicketCategory).filter(
                TicketCategory.event_id == event.id
            ).all()

            allocated += sum(
                category.quantity
                for category in categories
            )

            bookings = db.query(Booking).filter(
                Booking.event_id == event.id,
                Booking.status == "confirmed"
            ).all()

            sold += sum(
                booking.quantity
                for booking in bookings
            )

        result.append({
            "venue_id": venue.id,
            "venue_name": venue.name,
            "capacity": venue.capacity,
            "allocated_tickets": allocated,
            "tickets_sold": sold,
            "remaining_capacity": max(
                venue.capacity - sold, 0
            )
        })

    return result


# -----------------------------
# 4. Check-in Report
# -----------------------------

@router.get("/check-ins")
def checkin_report(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    events = db.query(Event).all()

    result = []

    for event in events:

        total_valid = db.query(Ticket).join(
            Booking,
            Ticket.booking_id == Booking.id
        ).filter(
            Booking.event_id == event.id,
            Booking.status == "confirmed",
            Ticket.status == "valid"
        ).count()

        checked_in = db.query(Ticket).join(
            Booking,
            Ticket.booking_id == Booking.id
        ).filter(
            Booking.event_id == event.id,
            Booking.status == "confirmed",
            Ticket.status == "valid",
            Ticket.checked_in == True
        ).count()

        result.append({
            "event_id": event.id,
            "event_name": event.title,
            "total_valid_tickets": total_valid,
            "checked_in": checked_in,
            "not_checked_in": total_valid - checked_in
        })

    return result


# -----------------------------
# 5. Recent Bookings
# -----------------------------

@router.get("/recent-bookings")
def recent_bookings(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    bookings = db.query(Booking).order_by(
        Booking.created_at.desc()
    ).limit(10).all()

    result = []

    for booking in bookings:

        event = db.query(Event).filter(
            Event.id == booking.event_id
        ).first()

        result.append({
            "booking_id": booking.id,
            "user_id": booking.user_id,
            "event_id": booking.event_id,
            "event_name": event.title if event else "Unknown",
            "quantity": booking.quantity,
            "total_amount": booking.total_amount,
            "payment_reference": booking.payment_reference,
            "refund_amount": booking.refund_amount,
            "refund_reference": booking.refund_reference,
            "status": booking.status,
            "created_at": booking.created_at
        })

    return result


# -----------------------------
# 6. Agent Communication Summary
# -----------------------------

@router.get("/agent-statistics")
def agent_statistics(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    total_messages = db.query(
        AgentMessage
    ).count()

    performatives = db.query(
        AgentMessage.performative,
        func.count(AgentMessage.id)
    ).group_by(
        AgentMessage.performative
    ).all()

    agent_messages = db.query(
        AgentMessage.sender,
        func.count(AgentMessage.id)
    ).group_by(
        AgentMessage.sender
    ).all()

    return {
        "total_messages": total_messages,
        "performative_statistics": {
            name: count
            for name, count in performatives
        },
        "agent_statistics": {
            name: count
            for name, count in agent_messages
        }
    }


# -----------------------------
# 7. Venue Hire Summary
# -----------------------------

@router.get("/venue-hires")
def venue_hire_summary(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    total = db.query(VenueHire).count()

    pending = db.query(VenueHire).filter(
        VenueHire.status == "pending"
    ).count()

    confirmed = db.query(VenueHire).filter(
        VenueHire.status == "confirmed"
    ).count()

    rejected = db.query(VenueHire).filter(
        VenueHire.status == "rejected"
    ).count()

    return {
        "total_requests": total,
        "pending": pending,
        "confirmed": confirmed,
        "rejected": rejected
    }
