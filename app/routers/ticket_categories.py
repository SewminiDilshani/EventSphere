
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.models import TicketCategory, Event, Booking, Ticket, Venue
from app.dependencies import require_role


router = APIRouter(
    prefix="/ticket-categories",
    tags=["Ticket Categories"]
)


# -----------------------------
# Request Schemas
# -----------------------------

class TicketCategoryCreate(BaseModel):
    event_id: int
    name: str = Field(min_length=2, max_length=100)
    price: float = Field(ge=0)
    quantity: int = Field(gt=0)


class TicketCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    price: float | None = Field(default=None, ge=0)
    quantity: int | None = Field(default=None, gt=0)


# -----------------------------
# Get Event Categories
# -----------------------------

@router.get("/event/{event_id}")
def get_event_categories(
    event_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("attendee", "admin"))
):
    event = db.query(Event).filter(
        Event.id == event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    categories = db.query(TicketCategory).filter(
        TicketCategory.event_id == event_id
    ).all()

    return [
        {
            "id": category.id,
            "event_id": category.event_id,
            "name": category.name,
            "price": category.price,
            "quantity": category.quantity
        }
        for category in categories
    ]


# -----------------------------
# Create Ticket Category
# Admin Only
# -----------------------------

@router.post("/")
def create_ticket_category(
    data: TicketCategoryCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    event = db.query(Event).filter(
        Event.id == data.event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if event.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Categories can only be added to draft events"
        )

    existing_categories = db.query(TicketCategory).filter(
        TicketCategory.event_id == data.event_id
    ).all()

    allocated_quantity = sum(
        category.quantity
        for category in existing_categories
    )

    venue = db.query(Venue).filter(
        Venue.id == event.venue_id
    ).first()

    if not venue:
        raise HTTPException(
            status_code=404,
            detail="Venue not found"
        )

    if allocated_quantity + data.quantity > venue.capacity:
        raise HTTPException(
            status_code=400,
            detail="Total ticket quantity exceeds venue capacity"
        )

    category = TicketCategory(
        event_id=data.event_id,
        name=data.name,
        price=data.price,
        quantity=data.quantity
    )

    try:
        db.add(category)
        db.commit()
        db.refresh(category)

        return {
            "message": "Ticket category created successfully",
            "id": category.id,
            "event_id": category.event_id,
            "name": category.name,
            "price": category.price,
            "quantity": category.quantity
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not create ticket category"
        )


# -----------------------------
# Update Ticket Category
# Admin Only
# -----------------------------

@router.put("/{category_id}")
def update_ticket_category(
    category_id: int,
    data: TicketCategoryUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    category = db.query(TicketCategory).filter(
        TicketCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(
            status_code=404,
            detail="Ticket category not found"
        )

    event = db.query(Event).filter(
        Event.id == category.event_id
    ).first()

    if not event:
        raise HTTPException(
            status_code=404,
            detail="Event not found"
        )

    if event.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Only draft event categories can be updated"
        )

    if data.name is not None:
        category.name = data.name

    if data.price is not None:
        category.price = data.price

    if data.quantity is not None:

        # Do not reduce quantity below already sold tickets
        sold_count = db.query(Ticket).join(
            Booking,
            Ticket.booking_id == Booking.id
        ).filter(
            Booking.event_id == category.event_id,
            Ticket.ticket_category_id == category.id,
            Booking.status == "confirmed",
            Ticket.status == "valid"
        ).count()

        if data.quantity < sold_count:
            raise HTTPException(
                status_code=400,
                detail="Quantity cannot be less than sold tickets"
            )

        venue = db.query(Venue).filter(
            Venue.id == event.venue_id
        ).first()

        other_categories = db.query(TicketCategory).filter(
            TicketCategory.event_id == category.event_id,
            TicketCategory.id != category.id
        ).all()

        other_quantity = sum(
            item.quantity for item in other_categories
        )

        if venue and other_quantity + data.quantity > venue.capacity:
            raise HTTPException(
                status_code=400,
                detail="Total ticket quantity exceeds venue capacity"
            )

        category.quantity = data.quantity

    try:
        db.commit()
        db.refresh(category)

        return {
            "message": "Ticket category updated successfully",
            "id": category.id,
            "event_id": category.event_id,
            "name": category.name,
            "price": category.price,
            "quantity": category.quantity
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update ticket category"
        )


# -----------------------------
# Delete Ticket Category
# Admin Only
# -----------------------------

@router.delete("/{category_id}")
def delete_ticket_category(
    category_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    category = db.query(TicketCategory).filter(
        TicketCategory.id == category_id
    ).first()

    if not category:
        raise HTTPException(
            status_code=404,
            detail="Ticket category not found"
        )

    event = db.query(Event).filter(
        Event.id == category.event_id
    ).first()

    if event and event.status != "draft":
        raise HTTPException(
            status_code=400,
            detail="Only draft event categories can be deleted"
        )

    ticket_exists = db.query(Ticket).filter(
        Ticket.ticket_category_id == category_id
    ).first()

    if ticket_exists:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a category that has tickets"
        )

    try:
        db.delete(category)
        db.commit()

        return {
            "message": "Ticket category deleted successfully"
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not delete ticket category"
        )
