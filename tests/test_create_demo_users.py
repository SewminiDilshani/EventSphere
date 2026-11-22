import pytest

from app import create_demo_users
from app.create_demo_users import get_demo_users


@pytest.mark.parametrize(
    ("role", "email"),
    [
        ("ADMIN", "admin@example.test"),
        ("STAFF", "staff@example.test"),
        ("ATTENDEE", "attendee@example.test"),
    ],
)
def test_get_demo_users_includes_configured_roles(monkeypatch, role, email):
    emails = {
        "ADMIN": "admin@example.test",
        "STAFF": "staff@example.test",
        "ATTENDEE": "attendee@example.test",
    }

    for configured_role, configured_email in emails.items():
        monkeypatch.setenv(f"DEMO_{configured_role}_EMAIL", configured_email)
        monkeypatch.setenv(f"DEMO_{configured_role}_PASSWORD", "LocalTest123")

    user = next(
        item for item in get_demo_users()
        if item["role"] == role.lower()
    )

    assert user["email"] == email
    assert user["password"] == "LocalTest123"


def test_create_demo_users_if_configured_skips_when_no_demo_variables(
    monkeypatch,
):
    for role in ("ADMIN", "STAFF", "ATTENDEE"):
        monkeypatch.delenv(f"DEMO_{role}_EMAIL", raising=False)
        monkeypatch.delenv(f"DEMO_{role}_PASSWORD", raising=False)

    monkeypatch.setattr(
        create_demo_users,
        "create_demo_users",
        lambda: pytest.fail("Demo users should not be created without config"),
    )

    create_demo_users.create_demo_users_if_configured()


def test_create_demo_users_if_configured_creates_when_configured(monkeypatch):
    for role in ("ADMIN", "STAFF", "ATTENDEE"):
        monkeypatch.setenv(f"DEMO_{role}_EMAIL", f"{role.lower()}@example.test")
        monkeypatch.setenv(f"DEMO_{role}_PASSWORD", "LocalTest123")

    calls = []
    monkeypatch.setattr(
        create_demo_users,
        "create_demo_users",
        lambda: calls.append(True),
    )

    create_demo_users.create_demo_users_if_configured()

    assert calls == [True]
