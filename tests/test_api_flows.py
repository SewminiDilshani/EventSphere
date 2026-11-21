from datetime import datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.migrations import (
    ensure_booking_refund_columns,
    ensure_event_cover_url_column,
    ensure_ticket_category_column
)
from app.models import (
    Booking,
    Event,
    Ticket,
    TicketCategory,
    User,
    Venue,
    VenueHire
)
from app.routers.auth import password_hash
from app.timeutils import get_local_now, to_local_naive


@pytest.fixture
def api():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    test_sessions = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine
    )

    def override_get_db():
        db = test_sessions()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            yield client, test_sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def add_user(session_factory, email, role, password="Password123"):
    with session_factory() as db:
        user = User(
            name=f"Test {role.title()}",
            email=email,
            password_hash=password_hash.hash(password),
            role=role,
            is_active=True
        )
        db.add(user)
        db.commit()
        return user.id


def add_event(session_factory, status="published", capacity=2):
    with session_factory() as db:
        venue = Venue(
            name="Test Hall",
            location="Vavuniya",
            capacity=capacity,
            hourly_rate=0,
            is_open_for_hire=True
        )
        db.add(venue)
        db.flush()

        event = Event(
            title="Test Concert",
            category="Music",
            venue_id=venue.id,
            start_time=datetime.now() + timedelta(days=2),
            end_time=datetime.now() + timedelta(days=2, hours=2),
            status=status
        )
        db.add(event)
        db.flush()

        category = TicketCategory(
            event_id=event.id,
            name="General",
            price=1000,
            quantity=capacity
        )
        db.add(category)
        db.commit()
        return event.id, category.id


def login(client, email, password="Password123"):
    response = client.post(
        "/auth/login",
        json={"email": email, "password": password}
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def test_draft_events_are_only_visible_to_admins(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    attendee_email = "attendee@example.test"
    staff_email = "staff@example.test"
    add_user(session_factory, admin_email, "admin")
    add_user(session_factory, attendee_email, "attendee")
    add_user(session_factory, staff_email, "staff")
    event_id, _ = add_event(session_factory, status="draft")
    published_event_id, _ = add_event(session_factory, status="published")

    assert client.get("/events/").status_code == 401
    assert client.get(f"/events/{event_id}").status_code == 404
    public_categories = client.get(
        f"/ticket-categories/event/{published_event_id}"
    )
    assert public_categories.status_code == 200
    assert public_categories.json()[0]["available_quantity"] == 2

    attendee_csrf = login(client, attendee_email)
    assert client.get(f"/events/{event_id}").status_code == 404
    assert client.get(
        f"/ticket-categories/event/{event_id}"
    ).status_code == 404
    assert client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": attendee_csrf}
    ).status_code == 200

    admin_csrf = login(client, admin_email)
    assert client.get(f"/events/{event_id}").status_code == 200
    assert client.get("/events/").status_code == 200
    assert client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": admin_csrf}
    ).status_code == 200
    login(client, staff_email)
    assert client.get(
        f"/staff/events/{event_id}/check-in-summary"
    ).status_code == 404
    assert client.get(
        f"/staff/events/{event_id}/check-ins"
    ).status_code == 404


def test_attendee_booking_prevents_overbooking_and_staff_double_checkin(api):
    client, session_factory = api
    attendee_email = "attendee@example.test"
    staff_email = "staff@example.test"
    add_user(session_factory, attendee_email, "attendee")
    add_user(session_factory, staff_email, "staff")
    event_id, category_id = add_event(session_factory, capacity=2)

    attendee_csrf = login(client, attendee_email)
    booking = client.post(
        "/bookings/",
        headers={"X-CSRF-Token": attendee_csrf},
        json={
            "event_id": event_id,
            "ticket_category_id": category_id,
            "quantity": 2
        }
    )
    assert booking.status_code == 200
    assert len(booking.json()["tickets"]) == 2

    overbooking = client.post(
        "/bookings/",
        headers={"X-CSRF-Token": attendee_csrf},
        json={
            "event_id": event_id,
            "ticket_category_id": category_id,
            "quantity": 1
        }
    )
    assert overbooking.status_code == 400
    assert overbooking.json()["detail"] == "Only 0 tickets are available"
    availability = client.get(
        f"/ticket-categories/event/{event_id}"
    )
    assert availability.json()[0]["available_quantity"] == 0

    assert client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": attendee_csrf}
    ).status_code == 200
    staff_csrf = login(client, staff_email)
    ticket_code = booking.json()["tickets"][0]
    scan_url = f"/tickets/scan/{ticket_code}?event_id={event_id}"

    first_scan = client.post(
        scan_url,
        headers={"X-CSRF-Token": staff_csrf}
    )
    assert first_scan.status_code == 200
    assert first_scan.json()["checked_in"] is True

    second_scan = client.post(
        scan_url,
        headers={"X-CSRF-Token": staff_csrf}
    )
    assert second_scan.status_code == 400
    assert "already been used" in second_scan.json()["detail"]


def test_cancelled_event_tickets_cannot_be_checked_in(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    attendee_email = "attendee@example.test"
    staff_email = "staff@example.test"
    add_user(session_factory, admin_email, "admin")
    add_user(session_factory, attendee_email, "attendee")
    add_user(session_factory, staff_email, "staff")
    event_id, category_id = add_event(session_factory, capacity=1)

    attendee_csrf = login(client, attendee_email)
    booking = client.post(
        "/bookings/",
        headers={"X-CSRF-Token": attendee_csrf},
        json={
            "event_id": event_id,
            "ticket_category_id": category_id,
            "quantity": 1
        }
    )
    assert booking.status_code == 200

    assert client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": attendee_csrf}
    ).status_code == 200
    admin_csrf = login(client, admin_email)
    cancelled = client.put(
        f"/events/{event_id}/cancel",
        headers={"X-CSRF-Token": admin_csrf}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["refunded_bookings"] == 1
    assert cancelled.json()["refund_amount"] == 1000

    with session_factory() as db:
        saved_booking = db.query(Booking).filter(
            Booking.event_id == event_id
        ).one()
        saved_ticket = db.query(Ticket).filter(
            Ticket.booking_id == saved_booking.id
        ).one()
        assert saved_booking.status == "cancelled"
        assert saved_booking.refund_amount == 1000
        assert saved_booking.refund_reference.startswith("SIM-REF-")
        assert saved_ticket.status == "cancelled"

    assert client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": admin_csrf}
    ).status_code == 200
    staff_csrf = login(client, staff_email)
    scan = client.post(
        f"/tickets/scan/{booking.json()['tickets'][0]}?event_id={event_id}",
        headers={"X-CSRF-Token": staff_csrf}
    )
    assert scan.status_code == 400
    assert scan.json()["detail"] == (
        "Ticket rejected. This ticket has been cancelled."
    )


def test_attendee_cancellation_persists_partial_simulated_refund(api):
    client, session_factory = api
    attendee_email = "attendee@example.test"
    add_user(session_factory, attendee_email, "attendee")
    event_id, category_id = add_event(session_factory, capacity=1)
    event_start = get_local_now() + timedelta(hours=12)

    with session_factory() as db:
        event = db.get(Event, event_id)
        event.start_time = event_start
        event.end_time = event_start + timedelta(hours=2)
        db.commit()

    csrf_token = login(client, attendee_email)
    booking = client.post(
        "/bookings/",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "event_id": event_id,
            "ticket_category_id": category_id,
            "quantity": 1
        }
    )
    assert booking.status_code == 200

    cancelled = client.put(
        f"/bookings/{booking.json()['booking_id']}/cancel",
        headers={"X-CSRF-Token": csrf_token}
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["refund_amount"] == 500
    assert cancelled.json()["refund_reference"].startswith("SIM-REF-")

    with session_factory() as db:
        saved_booking = db.get(Booking, booking.json()["booking_id"])
        assert saved_booking.status == "cancelled"
        assert saved_booking.refund_amount == 500


def test_booking_after_event_start_is_rejected(api):
    client, session_factory = api
    attendee_email = "attendee@example.test"
    add_user(session_factory, attendee_email, "attendee")
    event_id, category_id = add_event(session_factory, capacity=1)

    with session_factory() as db:
        event = db.get(Event, event_id)
        event.start_time = get_local_now() - timedelta(minutes=1)
        event.end_time = get_local_now() + timedelta(hours=2)
        db.commit()

    csrf_token = login(client, attendee_email)
    booking = client.post(
        "/bookings/",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "event_id": event_id,
            "ticket_category_id": category_id,
            "quantity": 1
        }
    )
    assert booking.status_code == 400
    assert booking.json()["detail"] == (
        "Event is no longer available for booking"
    )


def test_authenticated_mutations_require_csrf(api):
    client, session_factory = api
    email = "attendee@example.test"
    add_user(session_factory, email, "attendee")
    login(client, email)

    response = client.post(
        "/bookings/",
        json={
            "event_id": 1,
            "ticket_category_id": 1,
            "quantity": 1
        }
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Invalid or missing CSRF token"


def test_admin_can_deactivate_another_admin_while_remains_active(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    admin_id = add_user(session_factory, admin_email, "admin")
    csrf_token = login(client, admin_email)

    response = client.put(
        f"/admin/users/{admin_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={"is_active": False}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "You cannot deactivate your own account"
    )

    other_admin_id = add_user(
        session_factory,
        "other-admin@example.test",
        "admin"
    )
    response = client.put(
        f"/admin/users/{other_admin_id}",
        headers={"X-CSRF-Token": csrf_token},
        json={"is_active": False}
    )
    assert response.status_code == 200

    with session_factory() as db:
        assert db.get(User, admin_id).is_active is True
        assert db.get(User, other_admin_id).is_active is False


def test_legacy_ticket_table_migration_adds_foreign_key_column():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE ticket_categories (id INTEGER PRIMARY KEY)"
            )
            connection.exec_driver_sql(
                "CREATE TABLE tickets (id INTEGER PRIMARY KEY)"
            )

        ensure_ticket_category_column(engine)

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("tickets")
        }
        assert "ticket_category_id" in columns
    finally:
        engine.dispose()


def test_event_creation_cover_upload_and_public_display(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    add_user(session_factory, admin_email, "admin")

    with session_factory() as db:
        venue = Venue(
            name="Blue Hall",
            location="Colombo",
            capacity=80,
            hourly_rate=0,
            is_open_for_hire=True
        )
        db.add(venue)
        db.commit()
        venue_id = venue.id

    csrf_token = login(client, admin_email)
    starts_at = datetime.now() + timedelta(days=5)
    create_response = client.post(
        "/events/",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "title": "Summer Music Night",
            "category": "Music",
            "description": "An evening of live music.",
            "venue_id": venue_id,
            "start_time": starts_at.isoformat(),
            "end_time": (starts_at + timedelta(hours=3)).isoformat(),
            "ticket_categories": [{
                "name": "General",
                "price": 2500,
                "quantity": 60
            }]
        }
    )
    assert create_response.status_code == 200
    event_id = create_response.json()["event_id"]

    image = Image.new("RGB", (24, 16), color=(42, 91, 158))
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")
    upload_response = client.post(
        f"/events/{event_id}/cover",
        headers={"X-CSRF-Token": csrf_token},
        files={
            "file": (
                "summer.png",
                image_buffer.getvalue(),
                "image/png"
            )
        }
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["cover_image_url"] == (
        f"/events/{event_id}/cover"
    )

    draft_details = client.get(f"/events/{event_id}")
    assert draft_details.status_code == 200
    assert draft_details.json()["venue_name"] == "Blue Hall"
    assert draft_details.json()["venue_location"] == "Colombo"
    assert draft_details.json()["starting_price"] == 2500

    draft_image = client.get(f"/events/{event_id}/cover")
    assert draft_image.status_code == 200
    assert draft_image.headers["content-type"] == "image/png"
    assert draft_image.content == image_buffer.getvalue()

    assert client.put(
        f"/events/{event_id}/publish",
        headers={"X-CSRF-Token": csrf_token}
    ).status_code == 200
    public_event = client.get("/events/published").json()[0]
    assert public_event["cover_image_url"] == f"/events/{event_id}/cover"
    assert public_event["starting_price"] == 2500
    available_tickets = client.get(
        f"/ticket-categories/event/{event_id}"
    ).json()
    assert available_tickets[0]["available_quantity"] == 60
    assert available_tickets[0]["price"] == 2500

    assert client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": csrf_token}
    ).status_code == 200
    assert client.get(f"/events/{event_id}/cover").content == (
        image_buffer.getvalue()
    )


def test_event_cover_rejects_non_image_upload(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    add_user(session_factory, admin_email, "admin")
    event_id, _ = add_event(session_factory, status="draft")
    csrf_token = login(client, admin_email)

    response = client.post(
        f"/events/{event_id}/cover",
        headers={"X-CSRF-Token": csrf_token},
        files={"file": ("not-image.txt", b"not an image", "text/plain")}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "The uploaded file is not a valid image"
    )
    assert client.get(f"/events/{event_id}").json()["cover_image_url"] is None

    oversized = client.post(
        f"/events/{event_id}/cover",
        headers={"X-CSRF-Token": csrf_token},
        files={
            "file": (
                "oversized.png",
                b"x" * (5 * 1024 * 1024 + 1),
                "image/png"
            )
        }
    )
    assert oversized.status_code == 413


def test_favicon_asset_is_served(api):
    client, _ = api

    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/")


def test_events_and_venue_hires_cannot_overlap_or_exceed_venue_capacity(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    attendee_email = "attendee@example.test"
    add_user(session_factory, admin_email, "admin")
    add_user(session_factory, attendee_email, "attendee")

    start = datetime.now() + timedelta(days=5)
    end = start + timedelta(hours=2)
    with session_factory() as db:
        venue = Venue(
            name="Reserved Hall",
            location="Colombo",
            capacity=100,
            hourly_rate=5000,
            is_open_for_hire=True
        )
        db.add(venue)
        db.flush()
        db.add(VenueHire(
            user_id=db.query(User).filter(
                User.email == attendee_email
            ).one().id,
            venue_id=venue.id,
            purpose="Private function",
            guest_count=80,
            start_time=start,
            end_time=end,
            total_price=10000,
            status="confirmed"
        ))
        reserved_venue_id = venue.id
        db.commit()

    admin_csrf = login(client, admin_email)
    capacity_update = client.put(
        f"/venues/{reserved_venue_id}",
        headers={"X-CSRF-Token": admin_csrf},
        json={"capacity": 50}
    )
    assert capacity_update.status_code == 400
    assert "venue hire" in capacity_update.json()["detail"].lower()

    conflicting_event = client.post(
        "/events/",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "title": "Overlapping Event",
            "category": "Conference",
            "venue_id": reserved_venue_id,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "ticket_categories": [{
                "name": "General",
                "price": 0,
                "quantity": 20
            }]
        }
    )
    assert conflicting_event.status_code == 400
    assert "hire" in conflicting_event.json()["detail"].lower()

    event_id, _ = add_event(
        session_factory,
        status="published",
        capacity=20
    )
    with session_factory() as db:
        event = db.get(Event, event_id)
        attendee_start = event.start_time
        attendee_end = event.end_time
        event_venue_id = event.venue_id

    attendee_csrf = login(client, attendee_email)
    conflicting_hire = client.post(
        "/venue-hires/",
        headers={"X-CSRF-Token": attendee_csrf},
        json={
            "venue_id": event_venue_id,
            "purpose": "Event-adjacent gathering",
            "guest_count": 10,
            "start_time": attendee_start.isoformat(),
            "end_time": attendee_end.isoformat()
        }
    )
    assert conflicting_hire.status_code == 200
    assert conflicting_hire.json()["status"] == "unavailable"


def test_available_venue_hire_is_auto_confirmed_and_persisted(api):
    client, session_factory = api
    attendee_email = "attendee@example.test"
    add_user(session_factory, attendee_email, "attendee")
    event_id, _ = add_event(session_factory, capacity=50)

    with session_factory() as db:
        event = db.get(Event, event_id)
        event.venue.hourly_rate = 1500
        venue_id = event.venue_id
        db.commit()

    start = get_local_now() + timedelta(days=5)
    end = start + timedelta(hours=2)
    csrf_token = login(client, attendee_email)
    response = client.post(
        "/venue-hires/",
        headers={"X-CSRF-Token": csrf_token},
        json={
            "venue_id": venue_id,
            "purpose": "Student club reception",
            "guest_count": 25,
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }
    )

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"
    assert response.json()["total_price"] == 3000

    with session_factory() as db:
        hire = db.get(VenueHire, response.json()["hire_id"])
        assert hire.status == "confirmed"
        assert hire.total_price == 3000


def test_api_string_limits_match_database_columns(api):
    client, session_factory = api
    admin_email = "admin@example.test"
    attendee_email = "attendee@example.test"
    add_user(session_factory, admin_email, "admin")
    add_user(session_factory, attendee_email, "attendee")

    admin_csrf = login(client, admin_email)
    long_venue_name = client.post(
        "/venues/",
        headers={"X-CSRF-Token": admin_csrf},
        json={
            "name": "V" * 151,
            "location": "Colombo",
            "capacity": 50,
            "hourly_rate": 0
        }
    )
    assert long_venue_name.status_code == 422

    attendee_csrf = login(client, attendee_email)
    future = (datetime.now() + timedelta(days=3)).isoformat()
    long_hire_purpose = client.post(
        "/venue-hires/",
        headers={"X-CSRF-Token": attendee_csrf},
        json={
            "venue_id": 1,
            "purpose": "P" * 256,
            "guest_count": 1,
            "start_time": future,
            "end_time": (
                datetime.now() + timedelta(days=3, hours=1)
            ).isoformat()
        }
    )
    assert long_hire_purpose.status_code == 422


def test_legacy_event_table_migration_adds_cover_url_column():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE events (id INTEGER PRIMARY KEY)"
            )

        ensure_event_cover_url_column(engine)

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("events")
        }
        assert "cover_image_url" in columns
    finally:
        engine.dispose()


def test_legacy_bookings_table_migration_adds_refund_columns():
    engine = create_engine(
        "sqlite://",
        poolclass=StaticPool
    )
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE bookings (id INTEGER PRIMARY KEY)"
            )

        ensure_booking_refund_columns(engine)

        columns = {
            column["name"]
            for column in inspect(engine).get_columns("bookings")
        }
        assert {"refund_amount", "refund_reference"} <= columns
    finally:
        engine.dispose()


def test_utc_event_times_are_normalized_to_local_wall_time():
    utc_time = datetime.fromisoformat("2026-11-25T12:30:00+00:00")
    assert to_local_naive(utc_time) == datetime(2026, 11, 25, 18, 0)
