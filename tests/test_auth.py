
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.routers.auth import (
    RegisterData,
    LoginData,
    register,
    login,
    logout,
    get_my_account,
    password_hash
)


def create_db(user=None):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = user
    return db


def create_request(user_id=None):
    request = MagicMock()
    request.session = {}

    if user_id is not None:
        request.session["user_id"] = user_id

    return request


# 1. Registration Success Test

def test_register_success(monkeypatch):
    class FakeUser:
        email = "test@example.com"

        def __init__(self, **kwargs):
            self.id = 1
            self.name = kwargs["name"]
            self.email = kwargs["email"]
            self.password_hash = kwargs["password_hash"]
            self.role = kwargs["role"]
            self.is_active = kwargs["is_active"]

    monkeypatch.setattr("app.routers.auth.User", FakeUser)

    db = create_db()

    data = RegisterData(
        name="Test User",
        email="test@example.com",
        password="Test12345"
    )

    result = register(data, db)

    assert result["message"] == "Registration successful"
    assert result["user_id"] == 1
    assert result["role"] == "attendee"
    db.add.assert_called_once()
    db.commit.assert_called_once()


# 2. Registration Existing Email Test

def test_register_existing_email():
    existing_user = SimpleNamespace(email="test@example.com")
    db = create_db(existing_user)

    data = RegisterData(
        name="Test User",
        email="test@example.com",
        password="Test12345"
    )

    with pytest.raises(HTTPException) as error:
        register(data, db)

    assert error.value.status_code == 400
    assert error.value.detail == "Email already registered"


# 3. Login Success Test

def test_login_success():
    user = SimpleNamespace(
        id=1,
        name="Test User",
        email="test@example.com",
        password_hash=password_hash.hash("Test12345"),
        role="attendee",
        is_active=True
    )

    db = create_db(user)
    request = create_request()

    data = LoginData(
        email="test@example.com",
        password="Test12345"
    )

    result = login(data, request, db)

    assert result["message"] == "Login successful"
    assert result["user_id"] == 1
    assert result["role"] == "attendee"
    assert request.session["user_id"] == 1


# 4. Login Invalid Email Test

def test_login_invalid_email():
    db = create_db()
    request = create_request()

    data = LoginData(
        email="wrong@example.com",
        password="Test12345"
    )

    with pytest.raises(HTTPException) as error:
        login(data, request, db)

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid email or password"


# 5. Login Wrong Password Test

def test_login_wrong_password():
    user = SimpleNamespace(
        id=1,
        name="Test User",
        email="test@example.com",
        password_hash=password_hash.hash("Correct123"),
        role="attendee",
        is_active=True
    )

    db = create_db(user)
    request = create_request()

    data = LoginData(
        email="test@example.com",
        password="Wrong123"
    )

    with pytest.raises(HTTPException) as error:
        login(data, request, db)

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid email or password"


# 6. Login Inactive Account Test

def test_login_inactive_account():
    user = SimpleNamespace(
        id=1,
        name="Test User",
        email="test@example.com",
        password_hash=password_hash.hash("Test12345"),
        role="attendee",
        is_active=False
    )

    db = create_db(user)
    request = create_request()

    data = LoginData(
        email="test@example.com",
        password="Test12345"
    )

    with pytest.raises(HTTPException) as error:
        login(data, request, db)

    assert error.value.status_code == 403
    assert error.value.detail == "Account is inactive"


# 7. Logout Success Test

def test_logout_success():
    request = create_request(user_id=1)

    result = logout(request)

    assert result["message"] == "Logout successful"
    assert request.session == {}


# 8. Get Account Without Login Test

def test_get_account_without_login():
    request = create_request()
    db = create_db()

    with pytest.raises(HTTPException) as error:
        get_my_account(request, db)

    assert error.value.status_code == 401
    assert error.value.detail == "Please login first"


# 9. Get Account User Not Found Test

def test_get_account_user_not_found():
    request = create_request(user_id=1)
    db = create_db()

    with pytest.raises(HTTPException) as error:
        get_my_account(request, db)

    assert error.value.status_code == 401
    assert error.value.detail == "User not found"


# 10. Get Account Success Test

def test_get_account_success():
    user = SimpleNamespace(
        id=1,
        name="Test User",
        email="test@example.com",
        role="attendee"
    )

    request = create_request(user_id=1)
    db = create_db(user)

    result = get_my_account(request, db)

    assert result["id"] == 1
    assert result["name"] == "Test User"
    assert result["email"] == "test@example.com"
    assert result["role"] == "attendee"
