from datetime import datetime
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("Asia/Colombo")


def to_local_naive(value: datetime) -> datetime:
    if value.utcoffset() is not None:
        return value.astimezone(LOCAL_TIMEZONE).replace(tzinfo=None)

    return value


def get_local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE).replace(tzinfo=None)
