# Runtime Validation Report

**Generated:** 2026-11-21  
**Target:** EventSphere

## Summary

| Check | Result | Evidence |
|---|---|---|
| Local startup | PASS | `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001`; `/health` returned 200 with database connected. |
| Pytest integration/unit suite | PASS, exit code 0 | 71 passed, 0 failed. Includes 16 agent tests, overbooking, duplicate check-in, refunds, booking cutoff, venue-hire conflicts, auto-confirmation, and favicon serving. |
| Python compilation | PASS | `python -m compileall -q app tests` |
| Mobile browser smoke | PARTIAL | Integrated browser at 375 px verified home, events, login, and password toggle; no horizontal overflow or page exceptions. Unauthenticated staff/admin requests were rejected. |
| Live deployment | PARTIAL | Public health/OpenAPI/events GETs returned 200. The live API does not expose the event-cover route and has zero published events. No production writes. |
| PostgreSQL verification | UNVERIFIED | Docker is unavailable and no isolated PostgreSQL test database was provided; local tests used SQLite. |

## Browser and Environment Evidence

- Node.js: `v24.22.0`.
- Docker: unavailable in this environment.
- Playwright CLI package: not installed; `npx --no-install playwright --version` reported that `playwright@1.65.1` was missing. The integrated browser was used for a smoke check, not a standalone automated E2E suite.
- At viewport width 375 px, `/index.html`, `/pages/events.html`, and `/pages/login.html` had no horizontal overflow or page exceptions.
- Password visibility toggle changed from “Show password” to “Hide password”.
- `/favicon.ico` returned 200 with an image content type after adding the missing asset.
- Staff and admin data requests returned 401 when unauthenticated.

## Production and Assignment Gaps

- Current source is not deployed; production OpenAPI lacks `POST /events/{event_id}/cover`.
- The deployed `/events/published` response contained zero events. Demo accounts and data were not seeded because authenticated deployment access and isolated staging were unavailable.
- VenueAgent and BookingAgent do not own all scheduling, booking inventory, timing, and refund decisions; API routes still enforce these rules.
- Waitlist expiry is implemented, but ticket re-offers and attendee claim/hold flows are not.
- NotificationAgent notifications are process-local and do not persist across restarts.
- The browser check was not a complete authenticated admin → attendee booking → staff scan → admin dashboard flow.

## Warnings

Pytest reported existing pytest-asyncio fixture-scope and Starlette/httpx deprecation warnings. They did not fail the suite.

**Overall:** NEEDS SIGN-OFF — local tests passed, but deployment synchronization, persistent agent notifications, waitlist re-offers, and PostgreSQL/live authenticated flows remain unverified or incomplete.
