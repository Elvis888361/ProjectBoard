# ProjectBoard

This is a small project more like how Trello works , Sign up, create projects, and drag tasks between Todo,
In Progress and Done. Two or more people on the same board see each other's changes without
refreshing.

Its one repo with everything(Monorepo): `backend/` (FastAPI + PostgreSQL), `frontend/` (React + Vite).
See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and [AI_USAGE.md](AI_USAGE.md) for
how I used AI.

## Run it

You need Docker. Nothing else.

```bash
docker compose up --build
```

Open **http://localhost:5173** and create an account. The database schema is applied
automatically on first boot, and compose waits for Postgres before starting the API, so
this works from a clean clone.

To see the real time updates, open the same board in two windows (one private, so you get
a second login) and drag a card in one.

For a real deployment, set your own secret otherwise a dev default is used:

```bash
JWT_SECRET=$(openssl rand -hex 32) docker compose up --build
```

Every environment variable is documented in [.env.example](.env.example). No secrets are
committed to the repo.

## Run the tests

```bash
cd backend && createdb taskboard_test
DATABASE_URL=postgresql://taskboard:taskboard@localhost:5432/taskboard_test \
  JWT_SECRET=test-secret pytest
cd frontend && npm install && npm test
```

**CI** runs on every push ([.github/workflows/ci.yml](.github/workflows/ci.yml)): lint and
tests for both backend and frontend, plus a job that runs `docker compose up` and checks
the app comes up proving it really works from a clean clone.

## What was built

Mapped to the brief's Section 3.

**Must have all done**
- Register and login (email/password), auth on every API call
- CRUD for projects and tasks (title, description, status, assignee, due date)
- Board view with drag between columns
- Real-time: one user's change appears on another's board without refreshing
- Validation and error handling on both client and server
- Automated tests (backend unit + API, frontend component)
- Runs with one command (`docker compose up`)
- CI that lints and tests on every push

**Should have all done**
- Search and filter tasks by text or assignee
- Optimistic UI: the card moves instantly and rolls back if the server rejects it
- Rate limiting on the login endpoint
- Loading, error and empty states, plus a live/reconnecting indicator

**Could have one done**
- Activity log per project (came almost free the real time layer is built on an event
  log, so the audit trail is a read of a table that already exists)

**Not built** pagination and dark mode (skipped for time), and everything in the brief's
"Won't do" list (multi-tenancy, roles, billing, email, mobile, offline).

## Known gaps

Full detail, with how I'd fix each, is in [ARCHITECTURE.md](ARCHITECTURE.md).

- No refresh-token rotation one 12-hour session, no revocation.
- The login rate limiter is per-process correct at one worker, which is what we run.
- Drag and drop is mouse only (the task dialog's status dropdown is the keyboard path).

## API

Base path `/api/v1`. Interactive docs at **http://localhost:8000/api/docs**. Every error
has the same shape: `{ "error": { "code", "message", "details" } }`.
