
import os
import secrets
import mimetypes

from dotenv import load_dotenv

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from sqlalchemy import text

# Load .env before importing application modules
load_dotenv()

from app.database import engine, Base
from app import models

from app.routers import auth
from app.routers import (
    admin,
    staff,
    venues,
    events,
    bookings,
    ticket_categories,
    tickets,
    venue_hires,
    dashboard
)

from app import agents


# =====================================================
# ENVIRONMENT CONFIGURATION
# =====================================================

ENVIRONMENT = os.getenv(
    "ENVIRONMENT",
    "development"
).lower()

SECRET_KEY = os.getenv("SECRET_KEY")

if not SECRET_KEY:
    if ENVIRONMENT == "production":
        raise RuntimeError(
            "SECRET_KEY must be configured in production"
        )

    SECRET_KEY = "development-only-secret-change-before-deployment"

COOKIE_SECURE = ENVIRONMENT == "production"


# =====================================================
# FRONTEND ORIGINS
# =====================================================

default_origins = (
    "http://127.0.0.1:5501,"
    "http://localhost:5501"
)

FRONTEND_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        default_origins
    ).split(",")
    if origin.strip()
]


# =====================================================
# DIRECTORY CONFIGURATION
# =====================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

FRONTEND_DIR = os.path.join(
    BASE_DIR,
    "frontend"
)


# =====================================================
# DATABASE TABLE CREATION
# =====================================================

Base.metadata.create_all(bind=engine)


# =====================================================
# FASTAPI APPLICATION
# =====================================================

app = FastAPI(
    title="EventSphere",
    description="Venue Booking and Digital Ticketing System",
    version="1.0.0"
)


# =====================================================
# CSRF PROTECTION
# =====================================================

class CSRFMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):

        safe_methods = {
            "GET",
            "HEAD",
            "OPTIONS",
            "TRACE"
        }

        public_paths = {
            "/auth/register",
            "/auth/login"
        }

        if (
            request.method not in safe_methods
            and request.url.path not in public_paths
        ):

            user_id = request.session.get("user_id")

            if user_id:

                session_token = request.session.get(
                    "csrf_token"
                )

                request_token = request.headers.get(
                    "X-CSRF-Token"
                )

                if (
                    not session_token
                    or not request_token
                    or not secrets.compare_digest(
                        str(session_token),
                        str(request_token)
                    )
                ):

                    return JSONResponse(
                        status_code=403,
                        content={
                            "detail": "Invalid or missing CSRF token"
                        }
                    )

        return await call_next(request)


# =====================================================
# MIDDLEWARE CONFIGURATION
# =====================================================

app.add_middleware(CSRFMiddleware)

app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="eventsphere_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=COOKIE_SECURE
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=[
        "GET",
        "POST",
        "PUT",
        "PATCH",
        "DELETE",
        "OPTIONS"
    ],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-CSRF-Token"
    ]
)


# =====================================================
# REGISTER API ROUTERS
# =====================================================

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(staff.router)
app.include_router(venues.router)
app.include_router(events.router)
app.include_router(bookings.router)
app.include_router(ticket_categories.router)
app.include_router(tickets.router)
app.include_router(venue_hires.router)
app.include_router(agents.router)
app.include_router(dashboard.router)


# =====================================================
# HEALTH CHECK
# =====================================================

@app.get("/health")
def health():

    try:

        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))

        return {
            "status": "OK",
            "database": "Connected"
        }

    except Exception:

        return JSONResponse(
            status_code=503,
            content={
                "status": "ERROR",
                "database": "Disconnected"
            }
        )

# =====================================================
# HOME REDIRECT
# =====================================================

@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse(url="/index.html")

# =====================================================
# FRONTEND STATIC FILES
# =====================================================

if not os.path.isdir(FRONTEND_DIR):
    raise RuntimeError(
        f"Frontend directory not found: {FRONTEND_DIR}"
    )

# Fix wrong MIME types (Windows registry can break these)
mimetypes.add_type("text/css", ".css")
mimetypes.add_type("application/javascript", ".js")


class FrontendFiles(StaticFiles):
    """Serve frontend files with the correct Content-Type."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)

        if path.endswith(".css"):
            response.headers["content-type"] = "text/css; charset=utf-8"
        elif path.endswith(".js"):
            response.headers["content-type"] = "application/javascript; charset=utf-8"

        # No caching while developing, so CSS changes show immediately
        if ENVIRONMENT != "production":
            response.headers["cache-control"] = "no-store"

        return response


app.mount(
    "/",
    FrontendFiles(
        directory=FRONTEND_DIR,
        html=True
    ),
    name="frontend"
)