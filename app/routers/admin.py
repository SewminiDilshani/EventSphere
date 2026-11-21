
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import get_db
from app.dependencies import require_role
from app.models import User, Event, Booking, Venue


router = APIRouter(
    prefix="/admin",
    tags=["Admin"]
)


# -----------------------------
# Update User Schema
# -----------------------------

class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    role: str | None = None
    is_active: bool | None = None


def removing_last_admin(db, user, new_role=None, new_is_active=None):
    removing_admin = (
        user.role == "admin"
        and user.is_active
        and (
            new_role not in (None, "admin")
            or new_is_active is False
        )
    )

    return (
        removing_admin
        and db.query(User).filter(
            User.role == "admin",
            User.is_active == True
        ).count() <= 1
    )


# -----------------------------
# Admin Dashboard Welcome
# -----------------------------

@router.get("/dashboard")
def admin_dashboard(
    user: User = Depends(require_role("admin"))
):
    return {
        "message": "Welcome to Admin Dashboard",
        "user": user.name,
        "role": user.role
    }


# -----------------------------
# View All Users
# -----------------------------

@router.get("/users")
def get_all_users(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    users = db.query(User).order_by(
        User.id.desc()
    ).all()

    return [
        {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active
        }
        for user in users
    ]


# -----------------------------
# View One User
# -----------------------------

@router.get("/users/{user_id}")
def get_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active
    }


# -----------------------------
# Update User
# -----------------------------

@router.put("/users/{user_id}")
def update_user(
    user_id: int,
    data: UserUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if user.id == current_user.id and data.is_active is False:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate your own account"
        )

    allowed_roles = [
        "admin",
        "staff",
        "attendee"
    ]

    if data.role is not None:
        if data.role not in allowed_roles:
            raise HTTPException(
                status_code=400,
                detail="Invalid user role"
            )

        if user.id == current_user.id and data.role != "admin":
            raise HTTPException(
                status_code=400,
                detail="You cannot remove your own admin role"
            )

    if removing_last_admin(
        db,
        user,
        new_role=data.role,
        new_is_active=data.is_active
    ):
        raise HTTPException(
            status_code=400,
            detail="At least one active admin account must remain"
        )

    if data.role is not None:
        user.role = data.role

    if data.name is not None:
        user.name = data.name

    if data.is_active is not None:
        user.is_active = data.is_active

    try:
        db.commit()
        db.refresh(user)

        return {
            "message": "User updated successfully",
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": user.role,
            "is_active": user.is_active
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not update user"
        )


# -----------------------------
# Deactivate User
# -----------------------------

@router.put("/users/{user_id}/deactivate")
def deactivate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    if user.id == current_user.id:
        raise HTTPException(
            status_code=400,
            detail="You cannot deactivate your own account"
        )

    if removing_last_admin(db, user, new_is_active=False):
        raise HTTPException(
            status_code=400,
            detail="At least one active admin account must remain"
        )

    user.is_active = False

    try:
        db.commit()

        return {
            "message": "User deactivated successfully",
            "user_id": user.id
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not deactivate user"
        )


# -----------------------------
# Activate User
# -----------------------------

@router.put("/users/{user_id}/activate")
def activate_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    user = db.query(User).filter(
        User.id == user_id
    ).first()

    if not user:
        raise HTTPException(
            status_code=404,
            detail="User not found"
        )

    user.is_active = True

    try:
        db.commit()

        return {
            "message": "User activated successfully",
            "user_id": user.id
        }

    except Exception:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Could not activate user"
        )


# -----------------------------
# System Overview
# -----------------------------

@router.get("/system-overview")
def system_overview(
    db: Session = Depends(get_db),
    current_user=Depends(require_role("admin"))
):
    return {
        "total_users": db.query(User).count(),
        "total_admins": db.query(User).filter(
            User.role == "admin"
        ).count(),
        "total_staff": db.query(User).filter(
            User.role == "staff"
        ).count(),
        "total_attendees": db.query(User).filter(
            User.role == "attendee"
        ).count(),
        "total_venues": db.query(Venue).count(),
        "total_events": db.query(Event).count(),
        "total_bookings": db.query(Booking).count()
    }
