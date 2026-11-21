
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.timeutils import get_local_now
from app.routers.bookings import (
    BookingCreate,
    create_booking,
    my_bookings,
    cancel_booking
)


def make_query(result=None, scalar_result=None):
    query = MagicMock()
    query.filter.return_value = query
    query.join.return_value = query
    query.with_for_update.return_value = query
    query.first.return_value = result
    query.all.return_value = result if isinstance(result, list) else []
    query.scalar.return_value = scalar_result
    return query


def make_user():
    return SimpleNamespace(id=1)


# 1. Quantity must be positive
def test_booking_quantity_must_be_positive():
    with pytest.raises(ValidationError):
        BookingCreate(
            event_id=1,
            ticket_category_id=1,
            quantity=0
        )


# 2. Quantity maximum is ten
def test_booking_quantity_maximum_is_ten():
    with pytest.raises(ValidationError):
        BookingCreate(
            event_id=1,
            ticket_category_id=1,
            quantity=11
        )


# 3. Event not found
def test_create_booking_event_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    data = BookingCreate(
        event_id=1,
        ticket_category_id=1,
        quantity=2
    )

    with pytest.raises(HTTPException) as error:
        create_booking(data, db, make_user())

    assert error.value.status_code == 404
    assert error.value.detail == "Event not found"


# 4. Event not published
def test_create_booking_event_not_published():
    event = SimpleNamespace(id=1, status="draft")

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = event

    data = BookingCreate(
        event_id=1,
        ticket_category_id=1,
        quantity=2
    )

    with pytest.raises(HTTPException) as error:
        create_booking(data, db, make_user())

    assert error.value.status_code == 400
    assert error.value.detail == "Event is not available"


# 5. Ticket category not found
def test_create_booking_category_not_found():
    event = SimpleNamespace(
        id=1,
        status="published",
        start_time=get_local_now() + timedelta(days=2)
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(event),
        make_query(None)
    ]

    data = BookingCreate(
        event_id=1,
        ticket_category_id=1,
        quantity=2
    )

    with pytest.raises(HTTPException) as error:
        create_booking(data, db, make_user())

    assert error.value.status_code == 404
    assert error.value.detail == "Ticket category not found"


# 6. Insufficient tickets
def test_create_booking_insufficient_tickets():
    event = SimpleNamespace(
        id=1,
        status="published",
        start_time=get_local_now() + timedelta(days=2)
    )

    category = SimpleNamespace(
        id=1,
        quantity=5,
        price=1000,
        name="Regular"
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(event),
        make_query(category),
        make_query(scalar_result=4),
        make_query(scalar_result=0)
    ]

    data = BookingCreate(
        event_id=1,
        ticket_category_id=1,
        quantity=2
    )

    with pytest.raises(HTTPException) as error:
        create_booking(data, db, make_user())

    assert error.value.status_code == 400
    assert error.value.detail == "Only 1 tickets are available"


# 7. Successful booking
def test_create_booking_success(monkeypatch):
    from app.routers import bookings
    ticket_codes = iter(["ticket-one", "ticket-two"])
    monkeypatch.setattr(
        bookings,
        "generate_ticket_code",
        lambda db: next(ticket_codes)
    )

    class FakeBooking:
        id = 10
        event_id = MagicMock()
        status = MagicMock()
        refund_amount = 0
        refund_reference = None

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class FakeTicket:
        id = 1
        booking_id = 1
        ticket_category_id = MagicMock()
        ticket_code = MagicMock()
        status = MagicMock()
        checked_in = MagicMock()

        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    monkeypatch.setattr(bookings, "Booking", FakeBooking)
    monkeypatch.setattr(bookings, "Ticket", FakeTicket)

    event = SimpleNamespace(
        id=1,
        title="Vavuniya Music Festival",
        status="published",
        start_time=get_local_now() + timedelta(days=2)
    )

    category = SimpleNamespace(
        id=1,
        quantity=100,
        price=1000,
        name="Regular"
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(event),
        make_query(category),
        make_query(scalar_result=0),
        make_query(scalar_result=0)
    ]

    data = BookingCreate(
        event_id=1,
        ticket_category_id=1,
        quantity=2
    )

    result = create_booking(data, db, make_user())

    assert result["message"] == "Booking successful"
    assert result["booking_id"] == 10
    assert result["event"] == "Vavuniya Music Festival"
    assert result["ticket_category"] == "Regular"
    assert result["quantity"] == 2
    assert result["total_amount"] == 2000
    assert len(result["tickets"]) == 2

    db.add.assert_called()
    db.flush.assert_called_once()
    db.commit.assert_called_once()


# 8. View booking history
def test_my_bookings_success():
    booking = SimpleNamespace(
        id=1,
        user_id=1,
        event_id=1,
        quantity=2,
        total_amount=2000,
        payment_reference="SIM-123456",
        status="confirmed",
        created_at="2026-11-15"
    )

    event = SimpleNamespace(title="Vavuniya Music Festival")

    db = MagicMock()
    db.query.side_effect = [
        make_query([booking]),
        make_query(event)
    ]

    result = my_bookings(db, make_user())

    assert len(result) == 1
    assert result[0]["booking_id"] == 1
    assert result[0]["event"] == "Vavuniya Music Festival"
    assert result[0]["quantity"] == 2
    assert result[0]["total_amount"] == 2000
    assert result[0]["status"] == "confirmed"


# 9. Booking not found during cancellation
def test_cancel_booking_not_found():
    db = MagicMock()
    db.get_bind.return_value.dialect.name = "sqlite"
    db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as error:
        cancel_booking(1, db, make_user())

    assert error.value.status_code == 404
    assert error.value.detail == "Booking not found"


# 10. Already cancelled booking
def test_cancel_booking_already_cancelled():
    booking = SimpleNamespace(
        id=1,
        user_id=1,
        status="cancelled"
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = booking

    with pytest.raises(HTTPException) as error:
        cancel_booking(1, db, make_user())

    assert error.value.status_code == 400
    assert error.value.detail == "Booking cannot be cancelled"


# 11. Successful booking cancellation
def test_cancel_booking_success():
    booking = SimpleNamespace(
        id=1,
        user_id=1,
        event_id=1,
        total_amount=1000,
        status="confirmed",
        refund_amount=0,
        refund_reference=None
    )

    ticket1 = SimpleNamespace(status="valid")
    ticket2 = SimpleNamespace(status="valid")
    event = SimpleNamespace(
        start_time=datetime.now() + timedelta(days=2)
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(booking),
        make_query([ticket1, ticket2]),
        make_query(event)
    ]

    result = cancel_booking(1, db, make_user())

    assert result["message"] == "Booking cancelled successfully"
    assert result["booking_id"] == 1
    assert result["status"] == "cancelled"
    assert result["refund_amount"] == 1000
    assert result["refund_reference"].startswith("SIM-REF-")
    assert "24 hours" in result["refund_policy"]

    assert booking.status == "cancelled"
    assert booking.refund_amount == 1000
    assert ticket1.status == "cancelled"
    assert ticket2.status == "cancelled"

    db.commit.assert_called_once()
