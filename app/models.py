
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Float,
    Text
)
from sqlalchemy.orm import relationship

from app.database import Base


# -----------------------------
# User Table
# -----------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(100), nullable=False)

    email = Column(
        String(150),
        unique=True,
        nullable=False,
        index=True
    )

    password_hash = Column(String(255), nullable=False)

    role = Column(
        String(20),
        default="attendee",
        nullable=False
    )

    is_active = Column(
        Boolean,
        default=True,
        nullable=False
    )


# -----------------------------
# Venue Table
# -----------------------------

class Venue(Base):
    __tablename__ = "venues"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String(150), nullable=False)

    location = Column(String(200), nullable=False)

    capacity = Column(Integer, nullable=False)

    description = Column(Text)

    image = Column(String(255))

    hourly_rate = Column(
        Float,
        default=0,
        nullable=False
    )

    is_open_for_hire = Column(
        Boolean,
        default=True,
        nullable=False
    )

    events = relationship(
        "Event",
        back_populates="venue"
    )


# -----------------------------
# Event Table
# -----------------------------

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True, index=True)

    title = Column(String(200), nullable=False)

    category = Column(String(100), nullable=False)

    description = Column(Text)

    venue_id = Column(
        Integer,
        ForeignKey("venues.id"),
        nullable=False
    )

    start_time = Column(DateTime, nullable=False)

    end_time = Column(DateTime, nullable=False)

    status = Column(
        String(20),
        default="draft",
        nullable=False
    )

    venue = relationship(
        "Venue",
        back_populates="events"
    )

    ticket_categories = relationship(
        "TicketCategory",
        back_populates="event"
    )


# -----------------------------
# Ticket Category Table
# -----------------------------

class TicketCategory(Base):
    __tablename__ = "ticket_categories"

    id = Column(Integer, primary_key=True, index=True)

    event_id = Column(
        Integer,
        ForeignKey("events.id"),
        nullable=False
    )

    name = Column(String(100), nullable=False)

    price = Column(Float, nullable=False)

    quantity = Column(Integer, nullable=False)

    event = relationship(
        "Event",
        back_populates="ticket_categories"
    )


# -----------------------------
# Booking Table
# -----------------------------

class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    event_id = Column(
        Integer,
        ForeignKey("events.id"),
        nullable=False
    )

    quantity = Column(Integer, nullable=False)

    total_amount = Column(Float, nullable=False)

    payment_reference = Column(String(150))

    status = Column(
        String(30),
        default="confirmed",
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.now,
        nullable=False
    )

    user = relationship("User")

    event = relationship("Event")

    tickets = relationship(
        "Ticket",
        back_populates="booking"
    )


# -----------------------------
# Ticket Table
# -----------------------------

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)

    booking_id = Column(
        Integer,
        ForeignKey("bookings.id"),
        nullable=False
    )

    ticket_category_id = Column(
        Integer,
        ForeignKey("ticket_categories.id"),
        nullable=False
    )

    ticket_code = Column(
        String(255),
        unique=True,
        nullable=False,
        index=True
    )

    status = Column(
        String(30),
        default="valid",
        nullable=False
    )

    checked_in = Column(
        Boolean,
        default=False,
        nullable=False
    )

    checked_in_at = Column(DateTime)

    booking = relationship(
        "Booking",
        back_populates="tickets"
    )

    ticket_category = relationship("TicketCategory")


# -----------------------------
# Private Venue Hire Table
# -----------------------------

class VenueHire(Base):
    __tablename__ = "venue_hires"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    venue_id = Column(
        Integer,
        ForeignKey("venues.id"),
        nullable=False
    )

    purpose = Column(String(255), nullable=False)

    guest_count = Column(Integer, nullable=False)

    start_time = Column(DateTime, nullable=False)

    end_time = Column(DateTime, nullable=False)

    total_price = Column(
        Float,
        default=0,
        nullable=False
    )

    status = Column(
        String(30),
        default="pending",
        nullable=False
    )

    user = relationship("User")

    venue = relationship("Venue")


# -----------------------------
# Agent Message Log Table
# -----------------------------

class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id = Column(Integer, primary_key=True, index=True)

    sender = Column(String(100), nullable=False)

    receiver = Column(String(100), nullable=False)

    performative = Column(String(30), nullable=False)

    content = Column(Text)

    conversation_id = Column(
        String(100),
        index=True
    )


# -----------------------------
# Waitlist Table
# -----------------------------

class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    event_id = Column(
        Integer,
        ForeignKey("events.id"),
        nullable=False
    )

    status = Column(
        String(30),
        default="waiting",
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.now,
        nullable=False
    )

    expires_at = Column(DateTime, nullable=False)

    user = relationship("User")

    event = relationship("Event")


# --------------------------------
# Persistent Agent State
# --------------------------------

class AgentState(Base):
    __tablename__ = "agent_states"

    id = Column(Integer, primary_key=True, index=True)

    agent_name = Column(
        String(100),
        unique=True,
        nullable=False
    )

    state_data = Column(
        Text,
        default="{}",
        nullable=False
    )

    updated_at = Column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
        nullable=False
    )


# --------------------------------
# Persistent User Notifications
# --------------------------------

class UserNotification(Base):
    __tablename__ = "user_notifications"

    id = Column(Integer, primary_key=True, index=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=False
    )

    message = Column(
        Text,
        nullable=False
    )

    notification_type = Column(
        String(50),
        default="general",
        nullable=False
    )

    is_read = Column(
        Boolean,
        default=False,
        nullable=False
    )

    created_at = Column(
        DateTime,
        default=datetime.now,
        nullable=False
    )

    user = relationship("User")
