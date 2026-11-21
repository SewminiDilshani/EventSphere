
import asyncio
import json

from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.dependencies import require_role

from app.models import (
    AgentMessage,
    Venue,
    Event,
    Booking,
    Ticket,
    User,
    WaitlistEntry
)


router = APIRouter(
    prefix="/agents",
    tags=["Intelligent Agents"]
)


# =====================================================
# BASE AGENT
# =====================================================

class BaseAgent:

    def __init__(self, name, goal):
        self.name = name
        self.goal = goal
        self.state = "active"

    def get_info(self):
        return {
            "name": self.name,
            "goal": self.goal,
            "state": self.state
        }


# =====================================================
# AGENT 1 - VENUE AGENT
# =====================================================

class VenueAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            "VenueAgent",
            "Check venue availability and capacity"
        )

    def check_venue(self, venue_id, db):

        if not venue_id:
            return "REFUSE", {
                "reason": "Venue ID is required"
            }

        venue = db.query(Venue).filter(
            Venue.id == venue_id
        ).first()

        if not venue:
            return "REFUSE", {
                "reason": "Venue not found"
            }

        if not venue.is_open_for_hire:
            return "REFUSE", {
                "reason": "Venue is not available for hire"
            }

        return "AGREE", {
            "venue_id": venue.id,
            "venue_name": venue.name,
            "capacity": venue.capacity,
            "hourly_rate": venue.hourly_rate,
            "message": "Venue is available"
        }


# =====================================================
# AGENT 2 - BOOKING AGENT
# =====================================================

class BookingAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            "BookingAgent",
            "Check booking status and availability"
        )

    def check_booking(self, booking_id, db):

        if not booking_id:
            return "REFUSE", {
                "reason": "Booking ID is required"
            }

        booking = db.query(Booking).filter(
            Booking.id == booking_id
        ).first()

        if not booking:
            return "REFUSE", {
                "reason": "Booking not found"
            }

        if booking.status != "confirmed":
            return "REFUSE", {
                "reason": "Booking is not confirmed",
                "status": booking.status
            }

        return "AGREE", {
            "booking_id": booking.id,
            "status": booking.status,
            "event_id": booking.event_id,
            "quantity": booking.quantity,
            "total_amount": booking.total_amount
        }


# =====================================================
# AGENT 3 - TICKET AGENT
# =====================================================

class TicketAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            "TicketAgent",
            "Validate digital tickets and prevent duplicate check-ins"
        )

    def validate_ticket(self, ticket_code, db):

        if not ticket_code:
            return "REFUSE", {
                "reason": "Ticket code is required"
            }

        ticket = db.query(Ticket).filter(
            Ticket.ticket_code == ticket_code
        ).first()

        if not ticket:
            return "REFUSE", {
                "reason": "Invalid ticket"
            }

        if ticket.status != "valid":
            return "REFUSE", {
                "reason": "Ticket is cancelled"
            }

        if getattr(ticket, "checked_in", False):
            return "REFUSE", {
                "reason": "Ticket already used"
            }

        booking_id = getattr(ticket, "booking_id", None)

        if not isinstance(booking_id, int):
            return "REFUSE", {
                "reason": "Booking is not confirmed"
            }

        booking = db.query(Booking).filter(
            Booking.id == booking_id
        ).first()

        if not booking or booking.status != "confirmed":
            return "REFUSE", {
                "reason": "Booking is not confirmed"
            }

        event = db.query(Event).filter(
            Event.id == booking.event_id
        ).first()

        if not event or event.status != "published":
            return "REFUSE", {
                "reason": "Event is not available"
            }

        return "AGREE", {
            "ticket_id": ticket.id,
            "ticket_status": ticket.status,
            "booking_id": booking_id,
            "message": "Ticket is valid"
        }


# =====================================================
# AGENT 4 - WAITLIST AGENT
# =====================================================

class WaitlistAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            "WaitlistAgent",
            "Manage waiting list and expire temporary holds"
        )

        self.waitlist = []

    def add_to_waitlist(self, user_id, event_id, db=None):

        now = datetime.now()

        item = {
            "user_id": user_id,
            "event_id": event_id,
            "created_at": now.isoformat(),
            "status": "waiting",
            "expires_at": (
                now + timedelta(minutes=15)
            ).isoformat()
        }

        if db is None:

            self.waitlist.append(item)

            return "AGREE", {
                "message": "User added to waiting list",
                "item": item
            }

        user = db.query(User).filter(
            User.id == user_id
        ).first()

        if not user:
            return "REFUSE", {
                "reason": "User not found"
            }

        event = db.query(Event).filter(
            Event.id == event_id
        ).first()

        if not event:
            return "REFUSE", {
                "reason": "Event not found"
            }

        existing = db.query(WaitlistEntry).filter(
            WaitlistEntry.user_id == user_id,
            WaitlistEntry.event_id == event_id,
            WaitlistEntry.status == "waiting"
        ).first()

        if existing:
            return "REFUSE", {
                "reason": "User is already in the waiting list"
            }

        entry = WaitlistEntry(
            user_id=user_id,
            event_id=event_id,
            status="waiting",
            created_at=now,
            expires_at=now + timedelta(minutes=15)
        )

        db.add(entry)
        db.flush()

        item["id"] = entry.id

        return "AGREE", {
            "message": "User added to database waiting list",
            "item": item
        }

    def expire_waitlist(self, db=None):

        now = datetime.now()

        if db is not None:

            entries = db.query(WaitlistEntry).filter(
                WaitlistEntry.status == "waiting",
                WaitlistEntry.expires_at <= now
            ).all()

            expired = []

            for entry in entries:

                entry.status = "expired"

                expired.append({
                    "id": entry.id,
                    "user_id": entry.user_id,
                    "event_id": entry.event_id,
                    "status": "expired",
                    "expires_at": entry.expires_at.isoformat()
                })

            db.flush()

            return expired

        for item in self.waitlist:

            expiry = datetime.fromisoformat(
                item["expires_at"]
            )

            if (
                item["status"] == "waiting"
                and now >= expiry
            ):
                item["status"] = "expired"

        return self.waitlist


# =====================================================
# AGENT 5 - NOTIFICATION AGENT
# =====================================================

class NotificationAgent(BaseAgent):

    def __init__(self):
        super().__init__(
            "NotificationAgent",
            "Process booking, ticket and waitlist notifications"
        )

        self.notifications = []

    def notify(self, message, user_id=None):

        notification = {
            "notification": message,
            "user_id": user_id,
            "delivery_status": "simulated",
            "created_at": datetime.now().isoformat()
        }

        self.notifications.append(notification)

        return "INFORM", notification

    def receive_notification(self, content):

        message = content.get(
            "message",
            "New agent information received"
        )

        return self.notify(
            message,
            content.get("user_id")
        )


# =====================================================
# CREATE AGENT OBJECTS
# =====================================================

venue_agent = VenueAgent()
booking_agent = BookingAgent()
ticket_agent = TicketAgent()
waitlist_agent = WaitlistAgent()
notification_agent = NotificationAgent()

agents = {
    "VenueAgent": venue_agent,
    "BookingAgent": booking_agent,
    "TicketAgent": ticket_agent,
    "WaitlistAgent": waitlist_agent,
    "NotificationAgent": notification_agent
}


# =====================================================
# ALLOWED PERFORMATIVES
# =====================================================

ALLOWED_PERFORMATIVES = {
    "REQUEST",
    "AGREE",
    "REFUSE",
    "PROPOSE",
    "INFORM",
    "FAILURE"
}


# =====================================================
# AGENT MESSAGE MODEL
# =====================================================

class AgentRequest(BaseModel):

    sender: str
    receiver: str
    performative: str
    content: dict = Field(default_factory=dict)
    conversation_id: str | None = Field(default=None, max_length=100)


# =====================================================
# SAVE MESSAGE TO DATABASE
# =====================================================

def save_message(
    db,
    sender,
    receiver,
    performative,
    content,
    conversation_id
):

    message = AgentMessage(
        sender=sender,
        receiver=receiver,
        performative=performative,
        content=json.dumps(
            content,
            default=str
        ),
        conversation_id=conversation_id
    )

    db.add(message)
    db.flush()

    return message


# =====================================================
# MESSAGE PROCESSING
# =====================================================

def process_agent_message(data, db):

    receiver = agents[data.receiver]
    content = data.content

    if data.performative == "REQUEST":

        if data.receiver == "VenueAgent":
            return receiver.check_venue(
                content.get("venue_id"),
                db
            )

        if data.receiver == "BookingAgent":
            return receiver.check_booking(
                content.get("booking_id"),
                db
            )

        if data.receiver == "TicketAgent":
            return receiver.validate_ticket(
                content.get("ticket_code"),
                db
            )

        if data.receiver == "WaitlistAgent":
            return receiver.add_to_waitlist(
                content.get("user_id"),
                content.get("event_id"),
                db
            )

        if data.receiver == "NotificationAgent":
            return receiver.notify(
                content.get("message", "Notification"),
                content.get("user_id")
            )

    if (
        data.performative == "INFORM"
        and data.receiver == "NotificationAgent"
    ):
        return receiver.receive_notification(content)

    if data.performative == "PROPOSE":
        return "AGREE", {
            "message": "Proposal received",
            "agent": receiver.name,
            "proposal": content
        }

    if data.performative == "FAILURE":
        return "INFORM", {
            "message": "Failure information received",
            "agent": receiver.name,
            "failure_details": content
        }

    return "INFORM", {
        "message": "Message received",
        "agent": receiver.name,
        "received_performative": data.performative
    }


# =====================================================
# AUTOMATIC NOTIFICATION FOR EXPIRED WAITLIST
# =====================================================

def notify_expired_entries(db, expired_entries):

    for entry in expired_entries:

        message_content = {
            "message": (
                "Your temporary waiting list entry has expired."
            ),
            "user_id": entry["user_id"],
            "event_id": entry["event_id"],
            "waitlist_id": entry["id"]
        }

        conversation_id = str(uuid4())

        save_message(
            db,
            "WaitlistAgent",
            "NotificationAgent",
            "INFORM",
            message_content,
            conversation_id
        )

        notification_agent.receive_notification(
            message_content
        )


# =====================================================
# VIEW ALL AGENTS
# =====================================================

@router.get("/status")
def agent_status(
    current_user=Depends(require_role("admin"))
):

    return [
        agent.get_info()
        for agent in agents.values()
    ]


# =====================================================
# SEND MESSAGE BETWEEN AGENTS
# =====================================================

@router.post("/message")
def send_agent_message(
    data: AgentRequest,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    if data.sender not in agents:
        raise HTTPException(
            status_code=400,
            detail="Unknown sender agent"
        )

    if data.receiver not in agents:
        raise HTTPException(
            status_code=400,
            detail="Unknown receiver agent"
        )

    if data.sender == data.receiver:
        raise HTTPException(
            status_code=400,
            detail="Sender and receiver cannot be the same agent"
        )

    if data.performative not in ALLOWED_PERFORMATIVES:
        raise HTTPException(
            status_code=400,
            detail="Invalid performative"
        )

    conversation_id = (
        data.conversation_id or str(uuid4())
    )

    try:

        save_message(
            db,
            data.sender,
            data.receiver,
            data.performative,
            data.content,
            conversation_id
        )

        response_performative, response_content = (
            process_agent_message(data, db)
        )

        save_message(
            db,
            data.receiver,
            data.sender,
            response_performative,
            response_content,
            conversation_id
        )

        db.commit()

        return {
            "conversation_id": conversation_id,
            "sender": data.receiver,
            "receiver": data.sender,
            "performative": response_performative,
            "content": response_content
        }

    except HTTPException:
        db.rollback()
        raise

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Agent message processing failed"
        )


# =====================================================
# VIEW AGENT COMMUNICATION LOG
# =====================================================

@router.get("/messages")
def get_agent_messages(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    messages = db.query(AgentMessage).order_by(
        AgentMessage.id.desc()
    ).all()

    return [
        {
            "id": message.id,
            "sender": message.sender,
            "receiver": message.receiver,
            "performative": message.performative,
            "content": message.content,
            "conversation_id": message.conversation_id
        }
        for message in messages
    ]


# =====================================================
# VIEW SIMULATED NOTIFICATIONS
# =====================================================

@router.get("/notifications")
def get_notifications(
    current_user=Depends(require_role("admin"))
):

    return notification_agent.notifications


# =====================================================
# MANUAL WAITLIST EXPIRY CHECK
# =====================================================

@router.post("/waitlist/expire")
def expire_waitlist(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):

    try:

        expired_entries = waitlist_agent.expire_waitlist(db)

        notify_expired_entries(
            db,
            expired_entries
        )

        db.commit()

        return {
            "message": "Waitlist expiry check completed",
            "expired_count": len(expired_entries),
            "expired_entries": expired_entries
        }

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Waitlist expiry failed"
        )


# =====================================================
# AUTOMATIC WAITLIST EXPIRY TIMER
# =====================================================

waitlist_task = None


async def automatic_waitlist_expiry():

    while True:

        db = SessionLocal()

        try:

            expired_entries = (
                waitlist_agent.expire_waitlist(db)
            )

            if expired_entries:

                notify_expired_entries(
                    db,
                    expired_entries
                )

                db.commit()

            else:
                db.rollback()

        except Exception as error:

            db.rollback()

            print(
                "Waitlist expiry error:",
                str(error)
            )

        finally:
            db.close()

        await asyncio.sleep(60)


# =====================================================
# START AUTOMATIC TIMER
# =====================================================

async def start_waitlist_timer():

    global waitlist_task

    if waitlist_task is None or waitlist_task.done():

        waitlist_task = asyncio.create_task(
            automatic_waitlist_expiry()
        )


# =====================================================
# STOP AUTOMATIC TIMER
# =====================================================

async def stop_waitlist_timer():

    global waitlist_task

    if waitlist_task is not None:

        waitlist_task.cancel()

        try:
            await waitlist_task

        except asyncio.CancelledError:
            pass

        waitlist_task = None
