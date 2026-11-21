from datetime import datetime, timedelta

from app.refunds import calculate_attendee_refund


def test_attendee_cancellation_refund_is_full_at_24_hours():
    now = datetime(2026, 11, 1, 12, 0)
    event_start = now + timedelta(hours=24)

    assert calculate_attendee_refund(1200, event_start, now) == 1200


def test_attendee_cancellation_refund_is_half_within_24_hours():
    now = datetime(2026, 11, 1, 12, 0)
    event_start = now + timedelta(hours=23, minutes=59)

    assert calculate_attendee_refund(1200, event_start, now) == 600


def test_attendee_cancellation_refund_is_zero_after_event_start():
    now = datetime(2026, 11, 1, 12, 0)
    event_start = now - timedelta(seconds=1)

    assert calculate_attendee_refund(1200, event_start, now) == 0
