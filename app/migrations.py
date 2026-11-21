from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.engine import Engine


def ensure_ticket_category_column(engine: Engine) -> None:
    if "tickets" not in inspect(engine).get_table_names():
        return

    column_names = {
        column["name"]
        for column in inspect(engine).get_columns("tickets")
    }

    if "ticket_category_id" in column_names:
        return

    try:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE tickets "
                "ADD COLUMN ticket_category_id INTEGER "
                "REFERENCES ticket_categories(id)"
            ))
    except SQLAlchemyError:
        # Another app worker may have completed the same migration at startup.
        updated_columns = {
            column["name"]
            for column in inspect(engine).get_columns("tickets")
        }
        if "ticket_category_id" not in updated_columns:
            raise


def ensure_event_cover_url_column(engine: Engine) -> None:
    if "events" not in inspect(engine).get_table_names():
        return

    column_names = {
        column["name"]
        for column in inspect(engine).get_columns("events")
    }

    if "cover_image_url" in column_names:
        return

    try:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE events "
                "ADD COLUMN cover_image_url VARCHAR(255)"
            ))
    except SQLAlchemyError:
        updated_columns = {
            column["name"]
            for column in inspect(engine).get_columns("events")
        }
        if "cover_image_url" not in updated_columns:
            raise


def ensure_booking_refund_columns(engine: Engine) -> None:
    if "bookings" not in inspect(engine).get_table_names():
        return

    column_names = {
        column["name"]
        for column in inspect(engine).get_columns("bookings")
    }

    additions = {
        "refund_amount": (
            "ALTER TABLE bookings ADD COLUMN refund_amount "
            "FLOAT NOT NULL DEFAULT 0"
        ),
        "refund_reference": (
            "ALTER TABLE bookings ADD COLUMN refund_reference "
            "VARCHAR(150)"
        )
    }

    for column_name, statement in additions.items():
        if column_name in column_names:
            continue

        try:
            with engine.begin() as connection:
                connection.execute(text(statement))
        except SQLAlchemyError:
            updated_columns = {
                column["name"]
                for column in inspect(engine).get_columns("bookings")
            }
            if column_name not in updated_columns:
                raise
