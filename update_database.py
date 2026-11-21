
from app.database import Base, engine
from app.migrations import (
    ensure_booking_refund_columns,
    ensure_event_cover_url_column,
    ensure_ticket_category_column
)
from app import models


Base.metadata.create_all(bind=engine)
ensure_ticket_category_column(engine)
ensure_event_cover_url_column(engine)
ensure_booking_refund_columns(engine)
print("Database schema is up to date.")
