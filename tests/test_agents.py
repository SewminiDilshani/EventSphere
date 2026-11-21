
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from app.agents import (
    BaseAgent,
    VenueAgent,
    BookingAgent,
    TicketAgent,
    WaitlistAgent,
    NotificationAgent,
    agents
)


# Base Agent Tests

def test_base_agent_info():
    agent = BaseAgent("TestAgent", "Test goal")

    info = agent.get_info()

    assert info["name"] == "TestAgent"
    assert info["goal"] == "Test goal"
    assert info["state"] == "active"


# Venue Agent Tests

def test_venue_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    result, content = VenueAgent().check_venue(1, db)

    assert result == "REFUSE"
    assert content["reason"] == "Venue not found"


def test_venue_not_available():
    venue = MagicMock()
    venue.is_open_for_hire = False

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = venue

    result, content = VenueAgent().check_venue(1, db)

    assert result == "REFUSE"
    assert content["reason"] == "Venue is not available for hire"


def test_venue_available():
    venue = MagicMock()
    venue.id = 1
    venue.name = "Vavuniya Conference Hall"
    venue.capacity = 500
    venue.is_open_for_hire = True

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = venue

    result, content = VenueAgent().check_venue(1, db)

    assert result == "AGREE"
    assert content["venue_id"] == 1
    assert content["capacity"] == 500


# Booking Agent Tests

def test_booking_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    result, content = BookingAgent().check_booking(1, db)

    assert result == "REFUSE"
    assert content["reason"] == "Booking not found"


def test_booking_not_confirmed():
    booking = MagicMock()
    booking.status = "pending"

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = booking

    result, content = BookingAgent().check_booking(1, db)

    assert result == "REFUSE"
    assert content["reason"] == "Booking is not confirmed"


def test_booking_confirmed():
    booking = MagicMock()
    booking.id = 1
    booking.status = "confirmed"

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = booking

    result, content = BookingAgent().check_booking(1, db)

    assert result == "AGREE"
    assert content["booking_id"] == 1
    assert content["status"] == "confirmed"


# Ticket Agent Tests

def test_ticket_not_found():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    result, content = TicketAgent().validate_ticket("ABC123", db)

    assert result == "REFUSE"
    assert content["reason"] == "Invalid ticket"


def test_ticket_cancelled():
    ticket = MagicMock()
    ticket.status = "cancelled"
    ticket.checked_in = False

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket

    result, content = TicketAgent().validate_ticket("ABC123", db)

    assert result == "REFUSE"
    assert content["reason"] == "Ticket is cancelled"


def test_ticket_already_used():
    ticket = MagicMock()
    ticket.status = "valid"
    ticket.checked_in = True

    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = ticket

    result, content = TicketAgent().validate_ticket("ABC123", db)

    assert result == "REFUSE"
    assert content["reason"] == "Ticket already used"


def test_ticket_valid():
    ticket = MagicMock()
    ticket.id = 1
    ticket.status = "valid"
    ticket.checked_in = False
    ticket.booking_id = 2

    booking = MagicMock()
    booking.status = "confirmed"
    booking.event_id = 3

    event = MagicMock()
    event.status = "published"

    db = MagicMock()
    ticket_query, booking_query, event_query = (
        MagicMock(),
        MagicMock(),
        MagicMock()
    )
    ticket_query.filter.return_value.first.return_value = ticket
    booking_query.filter.return_value.first.return_value = booking
    event_query.filter.return_value.first.return_value = event
    db.query.side_effect = [ticket_query, booking_query, event_query]

    result, content = TicketAgent().validate_ticket("ABC123", db)

    assert result == "AGREE"
    assert content["ticket_id"] == 1
    assert content["ticket_status"] == "valid"


def test_ticket_for_cancelled_event_is_refused():
    ticket = MagicMock()
    ticket.id = 1
    ticket.status = "valid"
    ticket.checked_in = False
    ticket.booking_id = 2

    booking = MagicMock()
    booking.status = "confirmed"
    booking.event_id = 3

    event = MagicMock()
    event.status = "cancelled"

    db = MagicMock()
    ticket_query, booking_query, event_query = (
        MagicMock(),
        MagicMock(),
        MagicMock()
    )
    ticket_query.filter.return_value.first.return_value = ticket
    booking_query.filter.return_value.first.return_value = booking
    event_query.filter.return_value.first.return_value = event
    db.query.side_effect = [ticket_query, booking_query, event_query]

    result, content = TicketAgent().validate_ticket("ABC123", db)

    assert result == "REFUSE"
    assert content["reason"] == "Event is not available"


# Waitlist Agent Tests

def test_add_to_waitlist():
    agent = WaitlistAgent()

    result, content = agent.add_to_waitlist(1, 10)

    assert result == "AGREE"
    assert content["item"]["user_id"] == 1
    assert content["item"]["event_id"] == 10
    assert content["item"]["status"] == "waiting"


def test_waitlist_expiry():
    agent = WaitlistAgent()

    agent.add_to_waitlist(1, 10)

    agent.waitlist[0]["expires_at"] = (
        datetime.now() - timedelta(minutes=1)
    ).isoformat()

    result = agent.expire_waitlist()

    assert result[0]["status"] == "expired"


# Notification Agent Tests

def test_notification_agent():
    result, content = NotificationAgent().notify("Booking confirmed")

    assert result == "INFORM"
    assert content["notification"] == "Booking confirmed"
    assert content["delivery_status"] == "simulated"


# Agent Registry Test

def test_all_agents_registered():
    assert "VenueAgent" in agents
    assert "BookingAgent" in agents
    assert "TicketAgent" in agents
    assert "WaitlistAgent" in agents
    assert "NotificationAgent" in agents
