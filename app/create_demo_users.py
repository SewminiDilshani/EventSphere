
from app.database import SessionLocal
from app.models import User
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()

db = SessionLocal()

demo_users = [
    {
        "name": "EventSphere Admin",
        "email": "admin@eventsphere.com",
        "password": "Admin12345",
        "role": "admin"
    },
    {
        "name": "EventSphere Staff",
        "email": "staff@eventsphere.com",
        "password": "Staff12345",
        "role": "staff"
    }
]

try:
    for item in demo_users:
        user = db.query(User).filter(
            User.email == item["email"]
        ).first()

        if user:
            user.name = item["name"]
            user.password_hash = password_hash.hash(item["password"])
            user.role = item["role"]
            user.is_active = True
        else:
            user = User(
                name=item["name"],
                email=item["email"],
                password_hash=password_hash.hash(item["password"]),
                role=item["role"],
                is_active=True
            )
            db.add(user)

    db.commit()
    print("Admin and Staff accounts created successfully!")

except Exception as error:
    db.rollback()
    print("Error:", error)

finally:
    db.close()
