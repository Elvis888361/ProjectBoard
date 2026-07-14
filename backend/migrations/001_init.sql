-- Initial schema. See ARCHITECTURE.md for the data-model reasoning.

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

-- Native enum: a text column would let the app write garbage, and a lookup table buys
-- runtime-configurable columns we don't want.
CREATE TYPE task_status AS ENUM ('todo', 'in_progress', 'done');

CREATE TABLE tasks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id  uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title       text        NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    description text        NOT NULL DEFAULT '',
    status      task_status NOT NULL DEFAULT 'todo',
    assignee_id uuid        REFERENCES users(id) ON DELETE SET NULL,
    due_date    date,
    position    text        NOT NULL,   -- base62 fractional index; ORDER BY, never parse
    version     integer     NOT NULL DEFAULT 1,   -- optimistic concurrency
    created_by  uuid        NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Exactly the board query. `id` breaks ties if two inserts land on the same position,
-- so the order is at least identical on every client.
CREATE INDEX tasks_board_idx ON tasks (project_id, status, position, id);
CREATE INDEX tasks_assignee_idx ON tasks (assignee_id) WHERE assignee_id IS NOT NULL;

-- ILIKE '%foo%' can't use a btree.
CREATE INDEX tasks_title_trgm_idx ON tasks USING gin (title gin_trgm_ops);

CREATE TABLE events (
    id         bigserial PRIMARY KEY,
    project_id uuid        NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    task_id    uuid,   -- not a FK: events outlive the task they describe
    type       text        NOT NULL,
    actor_id   uuid        REFERENCES users(id) ON DELETE SET NULL,
    payload    jsonb       NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX events_replay_idx ON events (project_id, id);
