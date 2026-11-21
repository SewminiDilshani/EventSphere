
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routers.tickets import my_tickets, scan_ticket


def make_query(result=None):
    query = MagicMock()
    query.filter.return_value = query
    query.with_for_update.return_value = query
    query.all.return_value = result if isinstance(result, list) else []
    query.first.return_value = result
    query.update.return_value = 1
    return query


def make_staff():
    return SimpleNamespace(id=2)


def make_attendee():
    return SimpleNamespace(id=1)


# 1. Attendee has no bookings
def test_my_tickets_no_bookings():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    result = my_tickets(db, make_attendee())

    assert result == []


# 2. Get attendee tickets with QR code
def test_my_tickets_success():
    booking = SimpleNamespace(
        id=10,
        user_id=1,
        event_id=1
    )

    ticket = SimpleNamespace(
        id=5,
        booking_id=10,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=False
    )

    event = SimpleNamespace(
        id=1,
        title="Vavuniya Music Festival",
        status="published"
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query([booking]),
        make_query([ticket]),
        make_query(event)
    ]

    result = my_tickets(db, make_attendee())

    assert len(result) == 1
    assert result[0]["ticket_id"] == 5
    assert result[0]["event"] == "Vavuniya Music Festival"
    assert result[0]["ticket_code"] == "TICKET-ABC123"
    assert result[0]["status"] == "valid"
    assert result[0]["checked_in"] is False

    qr_code = result[0]["qr_code"]

    assert qr_code.startswith("data:image/png;base64,")

    encoded_data = qr_code.split(",", 1)[1]
    decoded_data = base64.b64decode(encoded_data)

    assert decoded_data.startswith(b"\x89PNG")


# 3. Event not found while getting tickets
def test_my_tickets_event_not_found():
    booking = SimpleNamespace(
        id=10,
        user_id=1,
        event_id=1
    )

    ticket = SimpleNamespace(
        id=5,
        booking_id=10,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=False
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query([booking]),
        make_query([ticket]),
        make_query(None)
    ]

    result = my_tickets(db, make_attendee())

    assert len(result) == 1
    assert result[0]["event"] == "Unknown"


# 4. Invalid ticket code
def test_scan_ticket_not_found():
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"

    monkeypatch_db = MagicMock()
    monkeypatch_db.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as error:
        scan_ticket("WRONG-CODE", monkeypatch_db, make_staff())

    assert error.value.status_code == 404
    assert error.value.detail == "Invalid ticket. Ticket not found."


# 5. Cancelled ticket
def test_scan_cancelled_ticket(monkeypatch):
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"

    monkeypatch.setattr(tickets, "Ticket", FakeTicket)

    ticket = SimpleNamespace(
        id=5,
        ticket_code="TICKET-ABC123",
        status="cancelled",
        checked_in=False
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket

    with pytest.raises(HTTPException) as error:
        scan_ticket("TICKET-ABC123", db, make_staff())

    assert error.value.status_code == 400
    assert error.value.detail == (
        "Ticket rejected. This ticket has been cancelled."
    )


# 6. Ticket already used
def test_scan_ticket_already_used(monkeypatch):
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"
        id = 5
        status = "valid"
        checked_in = False

    monkeypatch.setattr(tickets, "Ticket", FakeTicket)

    ticket = SimpleNamespace(
        id=5,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=True
    )

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket

    with pytest.raises(HTTPException) as error:
        scan_ticket("TICKET-ABC123", db, make_staff())

    assert error.value.status_code == 400
    assert error.value.detail == (
        "Ticket rejected. This ticket has already been used."
    )


# 7. Booking is not valid
def test_scan_ticket_booking_not_valid(monkeypatch):
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"

    class FakeBooking:
        id = 10

    monkeypatch.setattr(tickets, "Ticket", FakeTicket)
    monkeypatch.setattr(tickets, "Booking", FakeBooking)

    ticket = SimpleNamespace(
        id=5,
        booking_id=10,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=False
    )

    booking = SimpleNamespace(
        id=10,
        event_id=1,
        status="cancelled"
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(ticket),
        make_query(booking)
    ]

    with pytest.raises(HTTPException) as error:
        scan_ticket("TICKET-ABC123", db, make_staff())

    assert error.value.status_code == 400
    assert error.value.detail == (
        "Ticket rejected. Booking is not confirmed."
    )


# 8. Booking not found
def test_scan_ticket_booking_not_found(monkeypatch):
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"

    class FakeBooking:
        id = 10

    monkeypatch.setattr(tickets, "Ticket", FakeTicket)
    monkeypatch.setattr(tickets, "Booking", FakeBooking)

    ticket = SimpleNamespace(
        id=5,
        booking_id=10,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=False
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(ticket),
        make_query(None)
    ]

    with pytest.raises(HTTPException) as error:
        scan_ticket("TICKET-ABC123", db, make_staff())

    assert error.value.status_code == 400
    assert error.value.detail == "Ticket rejected. Booking not found."


# 9. Event not found during scanning
def test_scan_ticket_event_not_found(monkeypatch):
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"

    class FakeBooking:
        id = 10

    class FakeEvent:
        id = 1
        status = "published"

    monkeypatch.setattr(tickets, "Ticket", FakeTicket)
    monkeypatch.setattr(tickets, "Booking", FakeBooking)
    monkeypatch.setattr(tickets, "Event", FakeEvent)

    ticket = SimpleNamespace(
        id=5,
        booking_id=10,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=False
    )

    booking = SimpleNamespace(
        id=10,
        event_id=1,
        status="confirmed"
    )

    db = MagicMock()
    db.query.side_effect = [
        make_query(ticket),
        make_query(booking),
        make_query(None)
    ]

    with pytest.raises(HTTPException) as error:
        scan_ticket("TICKET-ABC123", db, make_staff())

    assert error.value.status_code == 404
    assert error.value.detail == "Ticket rejected. Event not found."


# 10. Successful ticket check-in
def test_scan_ticket_success(monkeypatch):
    from app.routers import tickets

    class FakeTicket:
        ticket_code = "TICKET-ABC123"
        id = 5
        status = "valid"
        checked_in = False

    class FakeBooking:
        id = 10

    class FakeEvent:
        id = 1

    monkeypatch.setattr(tickets, "Ticket", FakeTicket)
    monkeypatch.setattr(tickets, "Booking", FakeBooking)
    monkeypatch.setattr(tickets, "Event", FakeEvent)

    ticket = SimpleNamespace(
        id=5,
        booking_id=10,
        ticket_code="TICKET-ABC123",
        status="valid",
        checked_in=False,
        checked_in_at=None
    )

    booking = SimpleNamespace(
        id=10,
        event_id=1,
        status="confirmed"
    )

    event = SimpleNamespace(
        id=1,
        title="Vavuniya Music Festival",
        status="published"
    )

    db = MagicMock()
    update_query = make_query()
    db.query.side_effect = [
        make_query(ticket),
        make_query(booking),
        make_query(event),
        update_query
    ]

    result = scan_ticket("TICKET-ABC123", db, make_staff())

    assert result["message"] == "Check-in successful"
    assert result["ticket_id"] == 5
    assert result["event"] == "Vavuniya Music Festival"
    assert result["checked_in"] is True

    update_query.update.assert_called_once()
    db.commit.assert_called_once()

