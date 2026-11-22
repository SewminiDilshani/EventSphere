import logging
import os

from app.database import SessionLocal
from app.models import User
from pwdlib import PasswordHash


logger = logging.getLogger(__name__)
password_hash = PasswordHash.recommended()


def get_demo_users():
    users = []

    for role, name in (
        ("ADMIN", "EventSphere Admin"),
        ("STAFF", "EventSphere Staff"),
        ("ATTENDEE", "EventSphere Attendee")
    ):
        email = os.getenv(f"DEMO_{role}_EMAIL", "").strip().lower()
        password = os.getenv(f"DEMO_{role}_PASSWORD", "")

        if not email or len(password) < 8:
            raise RuntimeError(
                f"Set DEMO_{role}_EMAIL and a DEMO_{role}_PASSWORD "
                "of at least 8 characters before creating demo accounts"
            )

        users.append({
            "name": name,
            "email": email,
            "password": password,
            "role": role.lower()
        })

    return users


def create_demo_users():
    users = get_demo_users()
    db = SessionLocal()

    try:
        for item in users:
            user = db.query(User).filter(
                User.email == item["email"]
            ).first()

            if user:
                logger.info(
                    "Demo account %s already exists; leaving it unchanged",
                    item["email"]
                )
                continue

            db.add(User(
                name=item["name"],
                email=item["email"],
                password_hash=password_hash.hash(item["password"]),
                role=item["role"],
                is_active=True
            ))

        db.commit()
        logger.info("Demo accounts created or already present")

    except Exception:
        db.rollback()
        logger.exception("Could not create demo accounts")
        raise

    finally:
        db.close()


def create_demo_users_if_configured():
    roles = ("ADMIN", "STAFF", "ATTENDEE")
    variable_names = (
        f"DEMO_{role}_{setting}"
        for role in roles
        for setting in ("EMAIL", "PASSWORD")
    )

    if any(os.getenv(name) is not None for name in variable_names):
        create_demo_users()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    create_demo_users()
