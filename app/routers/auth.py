
import secrets
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from pwdlib import PasswordHash

from app.database import get_db
from app.models import User


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)

password_hash = PasswordHash.recommended()


# --------------------------------
# Request Schemas
# --------------------------------

class RegisterData(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=5, max_length=150)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Name must contain at least two characters")
        return normalized


class LoginData(BaseModel):
    email: str
    password: str


# --------------------------------
# Email Validation
# --------------------------------

def normalize_email(email: str):
    email = email.strip().lower()

    if not re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        email
    ):
        raise HTTPException(
            status_code=400,
            detail="Invalid email address"
        )

    return email


# --------------------------------
# User Registration
# --------------------------------

@router.post("/register")
def register(
    data: RegisterData,
    db: Session = Depends(get_db)
):
    email = normalize_email(data.email)

    existing_user = db.query(User).filter(
        User.email == email
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    new_user = User(
        name=data.name.strip(),
        email=email,
        password_hash=password_hash.hash(data.password),
        role="attendee",
        is_active=True
    )

    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)

        return {
            "message": "Registration successful",
            "user_id": new_user.id,
            "name": new_user.name,
            "role": new_user.role
        }

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    except Exception:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail="Registration failed"
        )


# --------------------------------
# User Login
# --------------------------------

@router.post("/login")
def login(
    data: LoginData,
    request: Request,
    db: Session = Depends(get_db)
):
    email = normalize_email(data.email)

    user = db.query(User).filter(
        User.email == email
    ).first()

    if not user:
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not password_hash.verify(
        data.password,
        user.password_hash
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password"
        )

    if not getattr(user, "is_active", True):
        raise HTTPException(
            status_code=403,
            detail="Account is inactive"
        )

    request.session.clear()
    request.session["user_id"] = user.id

    csrf_token = secrets.token_urlsafe(32)
    request.session["csrf_token"] = csrf_token

    return {
        "message": "Login successful",
        "user_id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "csrf_token": csrf_token
    }


# --------------------------------
# Get CSRF Token
# --------------------------------

@router.get("/csrf-token")
def get_csrf_token(request: Request):
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please login first"
        )

    csrf_token = request.session.get("csrf_token")

    if not csrf_token:
        csrf_token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = csrf_token

    return {
        "csrf_token": csrf_token
    }


# --------------------------------
# User Logout
# --------------------------------

@router.post("/logout")
def logout(request: Request):
    request.session.clear()

    return {
        "message": "Logout successful"
    }


# --------------------------------
# Get Logged-in User
# --------------------------------

@router.get("/me")
def get_my_account(
    request: Request,
    db: Session = Depends(get_db)
):
    user_id = request.session.get("user_id")

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Please login first"
        )

    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        request.session.clear()

        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    if not getattr(user, "is_active", True):
        request.session.clear()

        raise HTTPException(
            status_code=403,
            detail="Account is inactive"
        )

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role
    }
