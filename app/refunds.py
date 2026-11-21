from datetime import datetime, timedelta

from app.timeutils import get_local_now, to_local_naive


ATTENDEE_REFUND_POLICY = (
    "100% when cancelled at least 24 hours before event start; "
    "50% when cancelled less than 24 hours before start; "
    "0% after the event starts. Organiser-cancelled events receive "
    "a full simulated refund."
)


def calculate_attendee_refund(
    total_amount: float,
    event_start: datetime,
    now: datetime | None = None
) -> float:
    event_start = to_local_naive(event_start)
    current_time = to_local_naive(now or get_local_now())
    time_until_start = event_start - current_time

    if time_until_start <= timedelta(0):
        return 0.0

    if time_until_start >= timedelta(hours=24):
        return round(float(total_amount), 2)

    return round(float(total_amount) * 0.5, 2)
