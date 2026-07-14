# ProjectBoard

A small project & task board. Users sign up, create projects, and drag tasks between
Todo / In Progress / Done. Two people on the same board see each other's changes
without refreshing.

Monorepo: `backend/` (FastAPI + PostgreSQL), `frontend/` (React + Vite).

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the real-time decision and the tradeoffs. Read this one.
- **[AI_USAGE.md](AI_USAGE.md)** — what I used AI for, what I rejected, what I verified.

---

## Running it

You need Docker. Nothing else.

```bash
git clone <this repo> && cd ProjectBoard
docker compose up --build
```

Then open **http://localhost:5173** and create an account.

That's the whole setup. The database schema is applied automatically on first boot (the
API runs its migrations at startup), and compose waits for Postgres to be healthy before
starting the API — so there's no race on a cold clone.

To see the real-time behaviour, open the same board in two browser windows (use a
private window for the second so you get a separate session), and drag a card in one.

`JWT_SECRET` defaults to a dev value in `docker-compose.yml`. For anything real, set it:

```bash
JWT_SECRET=$(openssl rand -hex 32) docker compose up --build
```

See [.env.example](.env.example) for every variable the app reads. No secrets are
committed.

### Running without Docker

```bash
# Postgres must be running and DATABASE_URL must point at it.
cd backend
pip install -e ".[dev]"
JWT_SECRET=dev-secret uvicorn app.main:app --reload

cd frontend
npm install && npm run dev     # Vite proxies /api to :8000, so it's one origin
```

---

## Tests

```bash
# Backend — needs a Postgres. 18 tests.
cd backend
createdb taskboard_test
DATABASE_URL=postgresql://taskboard:taskboard@localhost:5432/taskboard_test \
  JWT_SECRET=test-secret pytest

# Frontend — 5 tests.
cd frontend
npm test
```

The backend tests boot a real uvicorn server against a real Postgres. That's deliberate:
the in-process ASGI test transport **cannot** test this app, because it waits for the
ASGI response to complete and an SSE stream never completes. Three of the tests drive an
actual SSE connection through an actual `LISTEN/NOTIFY` round trip.

**CI** ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs on every push: ruff +
pytest against a Postgres service container, eslint + tsc + vitest + a production build,
and a third job that runs `docker compose up` and curls the health endpoint — because
"it runs from a clean clone" is the claim most likely to quietly rot.

---

## What's built

Mapped to the brief's Section 3.

### Must have — all done

| | |
|---|---|
| Registration & login, authenticated API | Argon2id passwords, JWT in an httpOnly cookie |
| CRUD for projects and tasks | Title, description, status, assignee, due date |
| Board view, move tasks between statuses | Drag and drop, plus a keyboard path via the task dialog |
| **Real-time propagation** | SSE + Postgres `LISTEN/NOTIFY`, with gap-free reconnect. [Why](ARCHITECTURE.md#the-real-time-decision) |
| Validation & error handling, both sides | One error shape across the API; inline messages, toasts, and rollback in the UI |
| Automated tests | 18 backend (unit + integration + real SSE), 5 frontend |
| One-command local run | `docker compose up` |
| CI running lint + tests | GitHub Actions, three jobs |

### Should have — all done

- Search and filter by text or assignee
- Optimistic UI: a dragged card moves instantly and reconciles with the server, rolling
  back with an explanation if the server rejects it
- Rate limiting on `POST /auth/login` (10 attempts/minute/IP)
- Loading, error, and empty states throughout, plus a live/reconnecting indicator on the
  board — a stale board is worse than an obviously broken one

### Could have — one done

- **Activity log** per project. This came almost free: the realtime layer is built on an
  append-only event table, so the audit trail is a `SELECT` against a table that already
  had to exist. `GET /api/v1/projects/{id}/activity`.

Not done: pagination (a board of tens of tasks doesn't need it), dark mode.

### Won't do — not built, per the brief

Multi-tenant orgs, roles beyond "any logged-in user can edit", billing, email, mobile,
offline support.

---

## Known gaps

Written down rather than hidden. Fuller versions with "what I'd do instead" are in
[ARCHITECTURE.md](ARCHITECTURE.md#known-gaps).

- **No refresh-token rotation.** A single 12-hour session cookie. Losing it means losing
  the session for 12 hours; there's no revocation. I chose the board over the auth
  ceremony.
- **The login rate limiter is in-process.** Correct at one worker, which is what we run.
  At two workers an attacker gets double the budget. Needs a shared counter.
- **Drag-and-drop is mouse-only.** Native HTML5 DnD, no library. The task dialog's status
  select is the keyboard path, so nothing is unreachable — but the drag itself isn't
  accessible, and a real product would use `dnd-kit` for that.
- **Task positions can grow without bound** if someone inserts into the same gap
  thousands of times. Bounded in practice by human dragging speed; a column-renumber
  endpoint is the fix and is ~15 lines. Not built.
- **Untested:** the rate limiter (it's module state — testing it means sleeping or
  reaching into a private deque), and the SSE reconnect *backoff* (the browser owns it;
  I verified replay-after-reconnect, which is the part I own).

---

## API

`/api/v1`, versioned from the start. Interactive docs at **http://localhost:8000/api/docs**.

Every error, without exception, looks like this:

```json
{ "error": { "code": "version_conflict", "message": "...", "details": { "current": {...} } } }
```

`code` is stable and machine-readable; the frontend switches on it. A `409` carries the
current server state in `details`, so a client that lost a race can reconcile without a
second round trip.

```
POST   /api/v1/auth/register            201  sets session cookie
POST   /api/v1/auth/login               200  rate limited
POST   /api/v1/auth/logout              204
GET    /api/v1/auth/me                  200 | 401
GET    /api/v1/users                    200  everyone is assignable (no roles, per brief)

GET    /api/v1/projects                 200
POST   /api/v1/projects                 201
GET    /api/v1/projects/{id}            200 | 404
DELETE /api/v1/projects/{id}            204

GET    /api/v1/projects/{id}/tasks      200  ?search= &status= &assignee_id=
POST   /api/v1/projects/{id}/tasks      201
GET    /api/v1/projects/{id}/activity   200  the event log, read back
GET    /api/v1/projects/{id}/events     200  text/event-stream  <- the realtime channel

GET    /api/v1/tasks/{id}               200 | 404
PATCH  /api/v1/tasks/{id}               200 | 409  requires `version`
POST   /api/v1/tasks/{id}/move          200 | 409  requires `version`; names neighbours, not a position
DELETE /api/v1/tasks/{id}               204

GET    /api/health                      200 | 503  checks Postgres, not just the process
```
