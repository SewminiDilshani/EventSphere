import pytest

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
