# ProjectBoard

A small project and task board. Sign up, create projects, drag tasks between Todo,
In Progress and Done. Two people on the same board see each other's changes without
refreshing.

Monorepo: `backend/` (FastAPI + Postgres), `frontend/` (React + Vite).

See [ARCHITECTURE.md](ARCHITECTURE.md) for the real-time decision and the tradeoffs,
and [AI_USAGE.md](AI_USAGE.md) for how I used AI.

## Running it

You need Docker, nothing else.

```bash
docker compose up --build
```

Open http://localhost:5173 and create an account. The schema is applied on first boot,
and compose waits for Postgres to be healthy before starting the API, so a cold clone
works.

To see the real-time part, open the same board in two windows (one private, so you get
a second session) and drag a card.

`JWT_SECRET` has a dev default in compose. For anything real, set it:

```bash
JWT_SECRET=$(openssl rand -hex 32) docker compose up --build
```

Every variable the app reads is in [.env.example](.env.example). No secrets in the repo.

Without Docker: run Postgres, point `DATABASE_URL` at it, then `pip install -e ".[dev]"`
and `uvicorn app.main:app --reload` in `backend/`, and `npm install && npm run dev` in
`frontend/`. Vite proxies `/api` to the backend so it's one origin.

## Tests

```bash
cd backend && createdb taskboard_test
DATABASE_URL=postgresql://taskboard:taskboard@localhost:5432/taskboard_test \
  JWT_SECRET=test-secret pytest          # 18 tests

cd frontend && npm test                  # 5 tests
```

The backend tests boot a real uvicorn server against a real Postgres. That's deliberate:
httpx's in-process ASGI transport waits for the response to complete, and an SSE stream
never completes, so it deadlocks on the events endpoint. Three of the tests drive a real
SSE connection through a real `LISTEN/NOTIFY` round trip.

CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs lint and tests on both
sides, plus a job that does `docker compose up` and curls the health endpoint — "it runs
from a clean clone" is the claim most likely to quietly rot.

## What's built

**Must have — all done.** Registration and login (Argon2id, JWT in an httpOnly cookie),
CRUD for projects and tasks, a board you can drag cards around, real-time propagation,
validation and error handling on both sides, tests, one-command run, CI.

**Should have — all done.** Search and filter by text or assignee. Optimistic drag: the
card moves instantly and rolls back with an explanation if the server rejects it. Rate
limiting on login. Loading, error and empty states, plus a live/reconnecting badge.

**Could have — one done.** An activity log per project. It came almost free, because the
real-time layer is built on an append-only event table, so the audit trail is a `SELECT`
against a table that already had to exist. Skipped pagination (a board of tens of tasks
doesn't need it) and dark mode.

**Won't do — not built, as asked.** Multi-tenancy, roles, billing, email, mobile, offline.

## Known gaps

Longer versions, with what I'd do instead, are in [ARCHITECTURE.md](ARCHITECTURE.md).

- **No refresh-token rotation.** One 12-hour session cookie, no revocation. I chose the
  board over the auth ceremony.
- **The login rate limiter is per-process.** Correct at one worker, which is what we run.
  At two, an attacker gets double the budget.
- **Drag and drop is mouse-only.** Native HTML5 DnD, no library. The task dialog has a
  status select, so nothing is unreachable by keyboard, but the drag itself isn't
  accessible. This is the gap I'm least comfortable with.
- **Task positions can grow** if something inserts into the same gap thousands of times.
  Not reachable by hand. A renumber endpoint fixes it; ~15 lines, not built.
- **Untested:** the rate limiter (it's module state) and the SSE reconnect backoff (the
  browser owns it — I tested the replay that follows it, which is the part I own).

## API

`/api/v1`. Interactive docs at http://localhost:8000/api/docs.

Every error looks the same:

```json
{ "error": { "code": "version_conflict", "message": "...", "details": { "current": {} } } }
```

`code` is stable and the frontend switches on it. A 409 carries the current server state
so a client that lost a race can reconcile without another round trip.

```
POST   /auth/register  /auth/login  /auth/logout      GET /auth/me
GET    /users

GET    /projects                POST   /projects
GET    /projects/{id}           DELETE /projects/{id}
GET    /projects/{id}/tasks     POST   /projects/{id}/tasks
GET    /projects/{id}/activity
GET    /projects/{id}/events    <- text/event-stream, the real-time channel

GET    /tasks/{id}
PATCH  /tasks/{id}              409 on a stale version
POST   /tasks/{id}/move         409 on a stale version
DELETE /tasks/{id}

GET    /api/health              checks Postgres, not just the process
```
