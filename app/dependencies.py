
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User


# -----------------------------
# Get Currently Logged-in User
# -----------------------------

def get_current_user(
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
            detail="Invalid user session"
        )

    if not user.is_active:
        request.session.clear()

        raise HTTPException(
            status_code=403,
            detail="Your account is inactive"
        )

    return user


# -----------------------------
# Check User Role
# -----------------------------

def require_role(*allowed_roles):

    valid_roles = {
        "admin",
        "staff",
        "attendee"
    }

    if not allowed_roles:
        raise ValueError(
            "At least one role must be specified"
        )

    if not set(allowed_roles).issubset(valid_roles):
        raise ValueError(
            "Invalid role specified"
        )

    def role_checker(
        current_user: User = Depends(get_current_user)
    ):

        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail="You do not have permission"
            )

        return current_user

    return role_checker
