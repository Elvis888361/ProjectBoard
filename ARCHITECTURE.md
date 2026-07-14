# Architecture

## Contents

- [The system](#the-system)
- [The real-time decision](#the-real-time-decision) ← the main event
- [The data model](#the-data-model)
- [Concurrency: what happens when two people drag the same card](#concurrency-what-happens-when-two-people-drag-the-same-card)
- [Other tradeoffs made under the clock](#other-tradeoffs-made-under-the-clock)
- [What I'd do at 10x and 100x](#what-id-do-at-10x-and-100x)
- [Known gaps](#known-gaps)

---

## The system

```
                    ┌──────────────────────────────────────┐
   Browser          │  nginx (prod) / Vite proxy (dev)     │
  ┌────────┐        │  Serves the SPA, proxies /api        │
  │ React  │───────▶│  ONE ORIGIN → the session cookie     │
  │        │        │  works with no CORS at all           │
  │ Tan-   │        └──────────────┬───────────────────────┘
  │ Stack  │                       │
  │ Query  │                       ▼
  │ cache  │        ┌──────────────────────────────────────┐
  └───┬────┘        │  FastAPI                             │
      │             │                                      │
      │  writes ───▶│  REST  /api/v1/…      (POST, PATCH)  │
      │             │                                      │
      │  reads  ◀───│  SSE   /projects/{id}/events         │
      │  (push)     │        └── EventBroker ──┐           │
      └─────────────│                          │           │
                    └──────────────┬───────────┼───────────┘
                                   │           │
                          writes    │           │ LISTEN board_events
                                   ▼           │ (dedicated connection,
                    ┌──────────────────────────┴───────────┐  outside the pool)
                    │  PostgreSQL                          │
                    │                                      │
                    │  users, projects, tasks              │
                    │  events  ← append-only, BIGSERIAL id │
                    │            written in the SAME txn   │
                    │            as the state change       │
                    │            NOTIFY fires on COMMIT    │
                    └──────────────────────────────────────┘
```

The one-sentence version: **writes are ordinary REST; the only thing pushed to the
browser is a resumable event log.**

---

## The real-time decision

### What I chose

**Server-Sent Events for the push channel, an append-only `events` table as the source
of truth, and Postgres `LISTEN/NOTIFY` as the broker.** Writes stay plain REST.

### First, the honest part: this is not what the industry does

I looked at what production board products actually built before deciding, and the
evidence points the *other way*:

| Product | Transport | Source |
|---|---|---|
| Linear | WebSocket | [Linear's sync engine](https://linear.app/now/scaling-the-linear-sync-engine) — delta packets, each with a monotonic `lastSyncId` |
| Figma | WebSocket | [How Figma's multiplayer works](https://www.figma.com/blog/how-figmas-multiplayer-technology-works/) |
| Trello | WebSocket (socket.io), with polling fallback | Atlassian's tech-stack post; they famously fell *back* to polling at launch when sockets buckled |
| Slack | WebSocket | [Slack engineering](https://slack.engineering/real-time-messaging/) — >5M simultaneous sessions |
| Asana | WebSocket | [Scaling LunaDB](https://asana.com/resources/scaling-lunadb) |

I could not find a single named production board product whose primary transport is SSE.
So if I claimed "SSE is what the pros do," I'd be wrong, and I'd rather say that than
have it found out.

**But look at what those teams actually had to build on top of WebSockets.** Linear
invented `lastSyncId` and gap detection. Asana's own write-up describes their pain as
"each websocket backed by a stateful client session that would be discarded when a
connection was broken, **requiring the client to re-subscribe to all data**." Figma
checkpoints every 30–60s. Every one of them independently rebuilt *sequencing, reconnect,
and replay* — because WebSocket gives you a byte pipe and nothing else. No reconnect, no
resume, no delivery semantics.

That is the actual insight. **The hard part of realtime is not the transport, it's the
log.** And once you accept that, the question becomes: given that I have to build a
sequenced, replayable event log anyway, which transport makes that easier?

### Why SSE wins *for this problem*

1. **The workload is asymmetric.** A board is read-heavy and mutation-light. Users drag a
   card every few minutes; they watch continuously. WebSockets give a bidirectional
   channel where only one direction carries traffic — and then you rebuild auth,
   validation, error shapes, and routing *inside* the socket protocol instead of reusing
   the REST layer that already exists. NodeBB's maintainers publicly regret exactly this
   and [migrated request/response traffic back to REST](https://news.ycombinator.com/item?id=30312897).

2. **`Last-Event-ID` is the replay mechanism, and the browser implements it for me.**
   Every event carries `id: <events.id>`, a monotonic `BIGSERIAL`. When the connection
   drops, `EventSource` reconnects on its own and sends the last id it saw back in a
   `Last-Event-ID` header. The server streams the gap out of the events table and the
   client is caught up. **This is Linear's `lastSyncId`, except the browser does half of
   it and it cost me about ten lines.** With WebSockets I would have hand-rolled the
   reconnect loop, the backoff, and the resume handshake myself — and I'd have got the
   backoff wrong.

3. **Reconnect is free and correct, not free and lossy.** This is the part I'd push back
   on hardest if challenged. A naive WebSocket board reconnects and starts receiving
   *new* events — silently missing everything that happened while it was away, with no
   way to detect the loss. The board just quietly disagrees with the database until
   someone refreshes. Here, the gap is impossible: the client always knows its cursor.

4. **The event log pays for itself twice.** Because propagation goes through a persisted
   log rather than a broadcast from the request handler, the activity feed
   (`GET /projects/{id}/activity`) is a `SELECT` against a table that already had to
   exist. A "could have" from the brief, delivered for free.

### The mechanism, precisely

```
PATCH /api/v1/tasks/{id}
  │
  ├─ BEGIN
  │    UPDATE tasks SET … , version = version + 1
  │      WHERE id = $1 AND version = $2        ← optimistic lock; 0 rows ⇒ 409
  │    INSERT INTO events (…) RETURNING id     ← same transaction
  │    SELECT pg_notify('board_events', '<project_id>:<event_id>')
  └─ COMMIT                                     ← notification fires here, or never
       │
       ▼
  EventBroker's LISTEN connection (one per worker, outside the pool)
       │
       ▼
  in-process asyncio.Queue for each SSE subscriber on that project
       │
       ▼
  id: 42
  event: task.moved
  data: {"payload": {"task": { … "version": 7 … }}}
```

Three properties, each load-bearing:

**The event row is written in the same transaction as the state change.** The log
therefore *cannot* disagree with the table. If the update rolls back, so does the event.
This is what makes the log trustworthy enough to replay from — and it's why I don't
broadcast from the request handler, which would let a message escape for a change that
then rolled back.

**`NOTIFY` carries an ID, never the row.** The payload cap is 8000 bytes, and exceeding
it doesn't drop the notification — [it aborts the writing
transaction](https://www.postgresql.org/docs/current/sql-notify.html). The docs say it
outright: *"it's best to put it in a database table and send the key of the record."*
An ID-only payload also dedupes for free within a transaction.

**`NOTIFY` is a latency optimisation, not the correctness mechanism.** It is at-most-once
with no persistence: if the listener is mid-reconnect when one fires, it's gone, and
there is no way to detect the loss. **Correctness comes from the client's cursor.** The
system is still correct with `NOTIFY` entirely disabled — it just gets slower. Every team
that has succeeded with `LISTEN/NOTIFY` built it this way (Graphile Worker, River,
GoodJob — which still polls every 10s as a backstop); the ones that treated it as a
delivery guarantee got burned.

### The limits of this design, stated before you ask

I'd rather name these than be caught by them.

- **`LISTEN/NOTIFY` serialises commits.** Every `NOTIFY`-bearing transaction takes an
  `AccessExclusiveLock` on a global object (`async.c: PreCommit_Notify`), so all such
  commits serialise instance-wide. This is real, it's still true in PG19, and it's what
  [took down Recall.ai](https://www.recall.ai/blog/postgres-listen-notify-does-not-scale)
  — at *tens of thousands of concurrent writers*. We have single digits. Four orders of
  magnitude of headroom.
- **On PG ≤ 18, a `NOTIFY` wakes every listening backend regardless of channel** — O(N)
  in listener count. Joel Jacobson's benchmark on pgsql-hackers: 9,126 TPS at 0 idle
  listeners, **238 TPS at 1,000**. This is why the listener count here is *one per
  worker*, not one per connected user. The pathological design — a Postgres listener per
  websocket — is the one this specifically avoids. (Fixed in PG19, commit `282b1cde`.)
- **`LISTEN` cannot go through a transaction-mode pooler.** PgBouncer's feature matrix
  says `LISTEN | Never`. It also cannot run on a replica. Hence the dedicated connection
  straight to the primary, outside the pool. asyncpg's pool runs `UNLISTEN *` on release,
  which would silently unsubscribe us — one of the nastier ways this could have failed.
- **SSE consumes one of the browser's ~6 connections per origin under HTTP/1.1.** Open
  six board tabs and the seventh — plus every `fetch` to that origin — stalls. HTTP/2
  fixes it via multiplexing, and nginx terminates HTTP/2, so production is fine. But
  `uvicorn` is HTTP/1.1-only, so **in local dev this limit is live.** This is the
  sharpest criticism of the choice and I want it on the record.

### What would flip me to WebSockets

Two things, named in advance:

1. **Presence, live cursors, or drag-in-progress previews.** Those are genuinely
   bidirectional and high-frequency. A board with card CRUD is not; a board with "Alice
   is dragging this card right now" is. The moment that's on the roadmap, SSE is the
   wrong shape.
2. **Losing HTTP/2 to the browser**, if multi-tab use turned out to be common.

Neither is true today, so I didn't build for either.

---

## The data model

```sql
users     (id, email CITEXT UNIQUE, password_hash, display_name, …)
projects  (id, name, description, created_by → users, …)
tasks     (id, project_id → projects, title, description,
           status task_status,        -- native enum: 'todo' | 'in_progress' | 'done'
           assignee_id → users, due_date,
           position TEXT,             -- lexicographic fractional index
           version INTEGER,           -- optimistic concurrency
           …)
events    (id BIGSERIAL, project_id → projects, task_id, type, actor_id, payload JSONB, …)

INDEX tasks (project_id, status, position, id)   -- exactly the board query
INDEX events (project_id, id)                    -- exactly the replay query
```

Decisions worth defending:

**No ORM.** Raw SQL over asyncpg, with numbered `.sql` migrations and a ~20-line runner.
The brief asked for a schema I'd thought about, and the fastest way to prove that is to
write the SQL. Every query in this app is one I can explain and `EXPLAIN`; there is no
lazy-loading and no N+1 hiding behind an attribute access. The cost is real and I'll name
it: no autogenerated migrations, and I hand-map rows to dicts. At a few dozen queries
that's fine. At a few hundred I'd want SQLAlchemy Core — still not the ORM — for
composable query building.

**`status` is a native Postgres enum**, not a text column (which would let the app write
garbage) and not a lookup table (which buys runtime-configurable columns — explicitly out
of scope). Adding a status later is `ALTER TYPE … ADD VALUE`, which is cheap.

**`events.task_id` is deliberately *not* a foreign key.** Events outlive the tasks they
describe: "Alice deleted 'Ship the thing'" must survive the task's deletion. A cascade
would erase the audit trail, which is the one thing an audit trail must not do.

**`position` is a string, not a number.** See below.

### Task ordering: fractional indexing

A task's position is a base62 string. Positions sort lexicographically, and you can
always generate a key strictly between any two existing keys — so **a drag writes exactly
one row.**

The alternative — integer positions, renumbering on insert — is easier to read and worse
in every way that matters: every move becomes an O(n) multi-row write, two concurrent
moves in the same column deadlock or collide, and you need a deferrable unique constraint
to survive the intermediate states. Jira threw away its linked-list ranker for exactly
these reasons and replaced it with LexoRank, which is this idea. Trello uses floats and
[renumbers a window of cards when they get too
close](https://news.ycombinator.com/item?id=10957165). Figma's
[fractional indexing](https://www.figma.com/blog/realtime-editing-of-ordered-sequences/)
is a string precisely to dodge Trello's float-precision drift.

I ported [David Greenspan's
algorithm](https://observablehq.com/@dgreensp/implementing-fractional-indexing) (the one
behind Replicache and tldraw) rather than take the dependency — it's ~100 lines and I
wanted to be able to reason about the edge cases. It's in
[`backend/app/core/ranking.py`](backend/app/core/ranking.py) and it is the most
thoroughly tested thing in the codebase, including a seeded fuzz test that does 300
random inserts and asserts the sort order still reproduces the board.

The subtlety worth knowing: the key has an **integer part and a fraction**, and the
integer part's first character encodes its own length. That's not decoration — it's what
makes *append* produce a constant-length key. A naive "always take the midpoint of (0,1)"
scheme grows the key by a character on every append, and appending is the single most
common operation on a board. There's a test for exactly that: 1000 appends, key stays ≤5
characters.

**Where it breaks:** repeatedly inserting into the *same gap* grows the key ~1 char per
insert. A human dragging cards will never get there; a bulk import or a script would. Jira
handles this with online rebalancing (rank ≥128 chars → schedule; ≥254 → block the
operation). I did not build that. The fix is a `POST /columns/{id}/renumber` endpoint that
regenerates the column's keys in one transaction — about fifteen lines — and I'd add it
the moment anything programmatic started writing to this API. I chose a button I can press
over a cron job I'd never watch.

---

## Concurrency: what happens when two people drag the same card

Every task carries a `version`. Every mutation must state the version it believed it was
editing, and the write is conditional:

```sql
UPDATE tasks SET …, version = version + 1
WHERE id = $1 AND version = $2
RETURNING id;
```

Zero rows means someone else got there first → **409**, with the current server state in
the response body so the client can reconcile without a second round trip. Nobody's write
is ever silently overwritten. This is the lost-update problem, and it's the only place in
this API where two *correct* clients can produce a wrong result, so it gets the most test
attention.

**Why 409 and not 412.** RFC 9110 reserves 412 for a *conditional request header*
(`If-Match`) evaluating false. Here the expected version travels in the JSON body, so no
precondition header was evaluated and 412 would be a misuse — 409 (conflict with current
resource state) is correct. I went with the body because the move endpoint already carries
a small intent object and splitting half of it into headers buys nothing. If I wanted to
be RFC-pure I'd emit `ETag: W/"7"` on GET and require `If-Match` on writes; that's the
cleaner REST citizen and it's a fine thing to argue for.

**Moves are relational, not absolute.** The client sends `before_id` / `after_id` — the
neighbours it wants to land between — and the **server** computes the position string.
Two clients can never fight over a number because neither of them picks it. This is what
Jira's and Asana's rank APIs both do. If a neighbour vanished mid-drag (deleted, or moved
by someone else), the server appends to the target column rather than 500ing or 409ing:
the user's intent — "put it in this column" — is still satisfiable.

**On the client**, three things stop a stale event from clobbering a fresh optimistic
update — the classic race that makes naive optimistic UIs flicker:

1. `cancelQueries` before applying the optimistic patch, so an in-flight refetch can't
   land on top of it.
2. **A version guard on every incoming SSE event**: if the event describes a version ≤ the
   one already in the cache, drop it. Because server versions are monotonic, out-of-order
   delivery becomes harmless *by construction* rather than by timing luck.
3. `onSuccess` overwrites the optimistic guess with the server's authoritative row —
   which also bumps the cached version, so the echo of our own change arriving over SSE a
   moment later is dropped by (2) instead of being re-applied.

Rollback on failure restores the exact pre-drag snapshot and shows a toast. Silently
reverting would be worse than not moving at all: the user would think their drag worked
and it just… didn't stick.

---

## Other tradeoffs made under the clock

### 1. Session in an httpOnly cookie, and no refresh-token rotation

**The cookie was forced by the realtime design, not chosen for taste.** The browser's
`EventSource` API [cannot set custom headers](https://github.com/whatwg/html/issues/2177)
— an open spec issue since 2016 — so a bearer token can't ride in an `Authorization`
header on the stream. That leaves three options: put the token in the query string (where
it lands in every access log and proxy trace), use a `fetch`-based EventSource polyfill
(unmaintained, and it pushes the token back into `localStorage` where XSS can read it), or
use a cookie. The cookie is `httpOnly` + `SameSite=Lax`, works for both REST and the
stream, and is unreadable from JavaScript.

The cost is CSRF surface, since the browser attaches the cookie to any request to this
origin. `SameSite=Lax` handles the common cases, but [OWASP is explicit that SameSite is
defence-in-depth, not the
control](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html),
so there's also an `Origin` check on every state-changing request. For a first-party SPA
served same-origin that's sufficient. A third-party integration posting on a user's behalf
would need a signed double-submit token instead.

**What I cut:** refresh-token rotation. One 12-hour access token, no revocation. If it
leaks, it's valid for 12 hours. **The risk:** no way to kick a compromised session.
**The fix:** a short (15 min) access token plus a rotating refresh token in a second
cookie, with a server-side token family so reuse detection can revoke the whole chain.
That's most of a day, and it's auth ceremony rather than the thing being evaluated. I
spent that day on the board.

### 2. The login rate limiter is in-process

A sliding window in a module-level dict. It is *correct at one worker*, which is what we
run — and I run one worker partly for this reason. At two workers, an attacker gets double
the budget. **The fix** is a shared counter: Redis, or a Postgres table with a window
bucket. About an hour. I spent that hour on the SSE replay path, which the brief weights
far more heavily.

I'm calling this out because it's the *same* class of mistake as an in-memory pub/sub —
per-process state that silently breaks on the second worker. I avoided it where it would
have been fatal (the event fan-out goes through Postgres) and accepted it where it's
merely a weakness.

### 3. No state-management library

TanStack Query, and no Redux/Zustand. Nearly all the state on the board is a cached copy
of something the server owns — which is exactly what TanStack Query is for. It gives
caching, request dedup, and optimistic mutation with rollback, all of which I'd otherwise
have hand-written. Putting server data in Redux would mean re-implementing that *and*
keeping a second copy of the truth in sync with the SSE stream. The genuinely client-side
state (which dialog is open, what's in the filter box) is small and local and lives in
`useState`. A global store here would be ceremony, not architecture.

### 4. Native HTML5 drag-and-drop, no library

Zero dependencies, about forty lines. **The cost is accessibility:** native DnD is not
keyboard-operable. I mitigated it — the task dialog has a plain status `<select>`, so
every action is reachable without a mouse — but the *drag* isn't accessible, and a real
product would use `dnd-kit` for the accessible sensors. This is the tradeoff I'm least
comfortable with, and the first thing I'd change with another day.

---

## What I'd do at 10x and 100x

**10x (hundreds of users, tens of concurrent boards).** Almost nothing changes, and that's
the point of the design. Add workers; the fan-out already goes through Postgres, so each
worker holds its own listener and serves its own subscribers. The two things I *would* fix
first: move the rate limiter to a shared counter (it's now actually wrong, not just
theoretically wrong), and add the column-renumber endpoint before position keys have time
to grow.

**100x (thousands of concurrent users).** The design starts to bend in two specific places,
and I'd rather name them than pretend it scales forever:

1. **Replace `LISTEN/NOTIFY` with Redis pub/sub or NATS.** Not for throughput — we're
   nowhere near the commit-serialisation limit — but because at that size you want the
   broker to be a thing you can scale and observe independently of your primary database.
   Note honestly that Redis pub/sub buys **zero** reliability over `LISTEN/NOTIFY`:
   identical at-most-once semantics, no replay. It buys operational independence. The
   replay path stays exactly where it is, because the event table is what makes the system
   correct, and that doesn't change.
2. **The events table becomes the bottleneck.** It grows forever. I'd partition it by
   month, add a retention window (30 days of replay is plenty — beyond that, a client is
   better off doing a full refetch, which is the escape hatch every one of these systems
   has), and move the "replay the gap" read onto a replica.

At that scale I'd also revisit the transport, because at thousands of concurrent users the
HTTP/1.1 connection limit and per-connection memory start to matter, and presence/cursors
are the kind of feature that shows up when boards get busy. That's the point at which the
industry answer — WebSockets — becomes the right answer, and the migration is contained:
the log, the cursor, and the replay logic all survive it unchanged. **The transport is the
part I designed to be replaceable.**

---

## Known gaps

| Gap | Risk | Fix |
|---|---|---|
| No refresh-token rotation | A leaked session cookie is valid for 12h; no revocation | Short access token + rotating refresh token with a server-side family; ~1 day |
| Rate limiter is per-process | 2 workers ⇒ 2x the attack budget | Shared counter in Redis or Postgres; ~1 hour |
| Drag-and-drop is mouse-only | Keyboard users can't drag (though the status select covers every action) | `dnd-kit` for accessible sensors; ~half a day |
| Position keys grow on repeated same-gap inserts | Not reachable by hand; a bulk import would do it | Column-renumber endpoint; ~15 lines |
| Events table grows forever | Slow replay queries eventually | Partition by month + 30-day retention |
| Rate limiter and SSE backoff untested | Regressions could slip | Rate limiter needs a shared store to be testable; backoff is the browser's, and I tested the replay that follows it |
| No pagination on the board | A 10,000-task board would load slowly | Not a real scenario for an internal tool; server-side filters already exist |

**On testing generally:** coverage is not the metric and I didn't chase it. I tested the
two things where being wrong is both likely and silent — the ranking algorithm (a subtle
bug there doesn't crash, it quietly scrambles everyone's board) and the optimistic
concurrency path (where the failure is losing a colleague's work). Everything else is
FastAPI and Pydantic doing their jobs, and I'd rather have 18 tests I can justify than 80
that pad a number.
