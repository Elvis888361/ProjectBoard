-- Initial schema.
--
-- Design notes that aren't obvious from the DDL:
--
-- * `tasks.position` is a lexicographic fractional index (base62 string), not a
--   number. Sorting is `ORDER BY position, id`. This lets a drag-and-drop write
--   exactly one row instead of renumbering the column. See app/core/ranking.py.
--
-- * `tasks.version` is bumped on every write and used for optimistic concurrency.
--   All updates are conditional on it, so a stale client gets a 409 rather than
--   silently clobbering someone else's edit.
--
-- * `events` is the spine of the realtime layer. Every mutation appends a row here
--   in the SAME transaction as the state change, so the log can never disagree with
--   the table. `id BIGSERIAL` gives clients a monotonic cursor to resume from.

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- index for the task search box

CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email         citext      NOT NULL UNIQUE,
    password_hash text        NOT NULL,
    display_name  text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE projects (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name        text        NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    description text        NOT NULL DEFAULT '',
    created_by  uuid        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Statuses are a native enum, not a lookup table and not a bare text column.
-- A lookup table would buy runtime-configurable columns, which the brief explicitly
-- scopes out; a text column would let the app write garbage. Adding a status later
-- is `ALTER TYPE ... ADD VALUE`, which is cheap.
CREATE TYPE task_status AS ENUM ('todo', 'in_progress', 'done');

CREATE TABLE tasks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       text        NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    description text        NOT NULL DEFAULT '',
    status      task_status NOT NULL DEFAULT 'todo',
    assignee_id uuid        REFERENCES users(id) ON DELETE SET NULL,
    due_date    date,
    position    text        NOT NULL,
    version     integer     NOT NULL DEFAULT 1,
    created_by  uuid        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- The board query is "give me every task in this project, ordered within its column",
-- so the index leads with (project_id, status, position). `id` is the tie-break for
-- the rare case where two concurrent inserts land on the same position: order is then
-- arbitrary but *identical on every client*, which is what stops the board flickering.
CREATE INDEX tasks_board_idx ON tasks (project_id, status, position, id);
CREATE INDEX tasks_assignee_idx ON tasks (assignee_id) WHERE assignee_id IS NOT NULL;

-- Text search for the filter box. A trigram index is overkill at this scale, but a
-- plain ILIKE '%foo%' can't use an index at all, and this is one line.
CREATE INDEX tasks_title_trgm_idx ON tasks USING gin (title gin_trgm_ops);

CREATE TABLE events (
    id         bigserial PRIMARY KEY,
    project_id uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id    uuid,          -- deliberately NOT a FK: events outlive the task they describe
    type       text        NOT NULL,
    actor_id   uuid        REFERENCES users(id) ON DELETE SET NULL,
    payload    jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX events_replay_idx ON events (project_id, id);
