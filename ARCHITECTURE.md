# Architecture

## The system

```
  Browser                nginx (prod) / Vite (dev)          FastAPI              Postgres
  ┌────────┐             ┌──────────────────────┐    ┌──────────────────┐   ┌──────────────┐
  │ React  │──writes────▶│ serves the SPA,      │───▶│ REST  /api/v1/…  │──▶│ users        │
  │ Tan-   │             │ proxies /api         │    │                  │   │ projects     │
  │ Stack  │◀──events────│                      │◀───│ SSE   /events    │   │ tasks        │
  │ Query  │             │ ONE ORIGIN, so the   │    │   └─ EventBroker │◀──│ events       │
  └────────┘             │ cookie works with    │    └──────────────────┘   │  (LISTEN)    │
                         │ no CORS at all       │                           └──────────────┘
                         └──────────────────────┘
```

In one sentence: writes are ordinary REST, and the only thing pushed to the browser is a resumable event log.

## The real-time decision

**Server-Sent Events, over an append-only event log, with Postgres `LISTEN/NOTIFY` as the broker.** Writes stay REST.

### The honest part first: this isn't what the industry does

I looked before deciding, and the evidence went against me. Linear, Trello and Jira all use WebSockets. So I'm not going to claim I picked what everyone else picked.

But look at what those teams had to build *on top of* WebSockets. Linear invented `lastSyncId` and gap detection. Asana's own write-up describes each socket being backed by a session that got thrown away on disconnect, "requiring the client to re-subscribe to all data". Figma checkpoints every 30–60 seconds. Every one of them independently rebuilt sequencing reconnect and replay because a WebSocket is a byte pipe and gives you none of it.

That's the actual insight: **the hard part is the log, not the transport.** And once I have to build a sequenced replayable log anyway, the question becomes which transport makes that easier.

### Why SSE, here

The workload is asymmetric. People watch a board constantly and drag a card every few minutes. A WebSocket gives a two-way channel where only one direction carries traffic, and then you rebuild auth, validation and error shapes *inside* the socket instead of reusing the REST layer that already exists.

And `Last-Event-ID` is the replay mechanism, implemented for me by the browser. Every event carries `id: <events.id>`, a monotonic `BIGSERIAL`. When the connection drops, `EventSource` reconnects on its own and sends back the last id it saw. We stream the gap out of the events table and the client is caught up. That is Linear's `lastSyncId` except the browser does half of it, and it cost about ten lines.

The reconnect is the part I'd defend hardest. A naive WebSocket board reconnects and starts receiving *new* events, silently missing everything that happened while it was away. It just quietly disagrees with the database until someone refreshes. Here the gap is impossible, because the client always knows its cursor.

### How it works

```
PATCH /api/v1/tasks/{id}
  ├─ BEGIN
  │    UPDATE tasks … WHERE id = $1 AND version = $2   ← 0 rows means someone else won
  │    INSERT INTO events (…) RETURNING id             ← same transaction
  │    SELECT pg_notify('board_events', '<project>:<event_id>')
  └─ COMMIT                                            ← the notify fires here, or never
       ↓
  the listener connection (one per worker, outside the pool)
       ↓
  an asyncio.Queue per SSE subscriber on that project
       ↓
  id: 42 / event: task.moved / data: {…"version": 7…}
```

Three things carry the design.

**The event is written in the same transaction as the change.** So the log can't disagree with the table — if the update rolls back, so does the event. That's what makes the log trustworthy enough to replay from, and it's why I don't broadcast from the request handler.

**`NOTIFY` carries an id, never the row.** The payload cap is 8000 bytes and overflowing it doesn't drop the notification, it *aborts the writing transaction*. The Postgres docs say it plainly: put it in a table and send the key.

**`NOTIFY` is a latency optimisation, not the correctness mechanism.** It's atmost once with no persistence if the listener is mid-reconnect when one fires, it's gone and there's no way to detect the loss. Correctness comes from the client's cursor. The system is still correct with `NOTIFY` switched off entirely; it just gets slower.

### What's wrong with it

On PG ≤18 a `NOTIFY` wakes every listening backend regardless of channel. Jacobson's benchmark on pgsql hackers: 9,126 TPS at zero idle listeners, **238 at a thousand**. Which is exactly why the listener count here is one per *worker*, not one per connected user. The pathological design is a Postgres listener per websocket, and this avoids it.

`LISTEN` can't go through a transaction mode pooler (PgBouncer's matrix says `Never`) and can't run on a replica. Hence the dedicated connection to the primary, outside the pool asyncpg's pool runs `UNLISTEN *` on release, which would have silently unsubscribed us.

And SSE eats one of the browser's ~6 connections per origin under HTTP/1.1. nginx terminates HTTP/2 so production is fine, but uvicorn is HTTP/1.1-only, so **in local dev the limit is live**. That's the sharpest criticism of the choice and I want it on the record.

### What would change my mind

Presence, live cursors, or drag in progress previews those are genuinely two-way and high-frequency, and SSE is the wrong shape for them. Or losing HTTP/2 to the browser, if multi tab use turned out to be common. Neither is true today.

## The data model

**No ORM.** The brief asked for a schema I'd actually thought about, and the fastest way to show that is to write the SQL. Every query here is one I can explain, and `EXPLAIN` on it is what the database runs no lazy loading, no N+1 behind an attribute access. The cost, named honestly: no autogenerated migrations, and I hand map rows. At a few dozen queries that's fine; at a few hundred I'd want SQLAlchemy Core (still not the ORM) for composable queries.

`status` is a native enum, not text (which would let the app write garbage) and not a lookup table (which buys runtime-configurable columns, explicitly out of scope).

`events.task_id` is deliberately **not** a foreign key. Events outlive the tasks they describe "Alice deleted 'Ship it'" has to survive the task's deletion.

## Two people, one card

Every task has a `version`, and every write is conditional:

Zero rows means someone else got there first, so we return **409 with the current server state** and the client repairs that one card instead of refetching the board. Nobody's write is ever silently overwritten. This is the lost update problem, and it's the only place in the API where two *correct* clients can produce a wrong result so it gets the most tests.

**409, not 412.** RFC 9110 reserves 412 for a conditional request *header* (`If-Match`) evaluating false. Our version is in the body, so no precondition header was evaluated. If I wanted to be RFC-pure I'd emit an `ETag` and require `If-Match`, which is a fine thing to argue for.

**Moves are relational.** The client names `before_id` / `after_id` the neighbours it wants to land between and the *server* computes the position. Two clients can't fight over a number neither of them picked. Jira and Asana both do it this way. If a neighbour vanished mid-drag, the server appends to the target column rather than failing: the user's intent is still satisfiable.

On the client, three things stop a stale event clobbering a fresh optimistic update the race that makes naive optimistic UIs flicker. `cancelQueries` before patching, so an in flight refetch can't land on top. A **version guard** on every incoming event: if it describes a version we already have, drop it. And `onSuccess` overwrites the optimistic guess with the server's row, which bumps the cached version, so the SSE echo of our own change gets dropped by the guard instead of re-applied.

## Other tradeoffs

**What I cut: refresh-token rotation.** One 12 hour token, no revocation. If it leaks, it's good for 12 hours. The fix is a short access token plus a rotating refresh token with a server side token family so reuse detection can revoke the chain. That's most of a day, and it's auth ceremony rather than the thing being evaluated. I spent the day on the board.

**The rate limiter is in-process.** Correct at one worker, which is what we run and I run one partly for this reason. At two, an attacker gets double the budget. The fix is a shared counter in Redis or Postgres, about an hour. I spent that hour on the SSE replay path. Worth naming because it's the *same* class of mistake as an in memory pub/sub: per process state that silently breaks on the second worker. I avoided it where it would have been fatal and accepted it where it's only a weakness.

**No state library.** TanStack Query, no Redux or Zustand. The board *is* server state, which is what TanStack Query is for it gives optimistic mutation with rollback, which I'd otherwise have hand rolled. Putting server data in Redux would mean reimplementing that and then keeping a second copy of the truth in sync with the SSE stream. The genuinely local state (open dialog, filter text) is `useState`.

**The session cookie was forced, not chosen.** `EventSource` cannot set an `Authorization`header an open spec issue since 2016. So a bearer token would have to travel in the SSE query string, where it lands in every access log. The alternatives were a token in the URL, an unmaintained fetch-based polyfill (which puts the token back in `localStorage` where XSS can read it), or a cookie. The cookie is httpOnly and `SameSite=Lax`, works for both REST and the stream, and is unreadable from JS. The cost is CSRF surface, so there's also an Origin check on every state changing request OWASP is explicit that SameSite is defence-in-depth, not the control.

**Native drag and drop, no library.** Zero dependencies, about forty lines. The cost is that it isn't keyboard accessible. I mitigated it — the task dialog has a status select, so nothing is unreachable — but the drag itself isn't accessible, and a real product would use `dnd-kit`. This is the tradeoff I'm least comfortable with and the first thing I'd change.

## 10x and 100x

**At 10x** (hundreds of users) almost nothing changes, and that's the point of the design. Add workers; the fan-out already goes through Postgres, so each worker holds its own listener and serves its own subscribers. Two things I'd fix first: move the rate limiter to a shared counter (it's now actually wrong, not just theoretically), and add the renumber endpoint before position keys have time to grow.

**At 100x** it bends in two places. I'd replace `LISTEN/NOTIFY` with Redis pub/sub or NATS not for throughput, we're nowhere near the commit serialisation limit, but because at that size you want the broker to scale and be observable independently of your primary database. Honestly: Redis pub/sub buys **zero** reliability over `LISTEN/NOTIFY`. Same atmost once semantics, no replay. It buys operational independence, and that's all. The replay path stays exactly where it is, because the event table is what makes the system correct.

And the events table grows forever. I'd partition it by month, keep a 30-day replay window (beyond that a client is better off doing a full refetch, which is the escape hatch every one of these systems has), and move the replay read onto a replica.

At that scale I'd revisit the transport too, because presence and cursors are exactly the kind of feature that shows up when boards get busy. That's the point at which the industry answer becomes the right answer — and the migration is contained. The log, the cursor and the replay logic all survive it unchanged. **The transport is the part I designed to be replaceable.**

## Known gaps

| Gap | Risk | Fix |
|----------------------------|-----------------------------------------------|------------------------------------------------|
| No refresh-token rotation | A leaked cookie is good for 12h, no revocation | Short access token + rotating refresh token; ~1 day |
| Rate limiter is per-process | Two workers, double the attack budget | Shared counter in Redis or Postgres; ~1 hour |
| Drag and drop is mouse-only | Keyboard users can't drag (the status select covers every action) | `dnd-kit`; ~half a day |
| Position keys grow on repeated same-gap inserts | Not reachable by hand; a bulk import would | Renumber endpoint; ~15 lines |
| Events table grows forever | Replay queries slow eventually | Partition by month, 30-day retention |
| Rate limiter and SSE backoff untested | Regressions could slip | The limiter needs a shared store to be testable; backoff is the browser's |

On testing generally: coverage isn't the metric and I didn't chase it. I tested the two places where being wrong is both likely and silent — the ranking algorithm (a subtle bug there doesn't crash, it quietly scrambles everyone's board) and optimistic concurrency (where the failure is losing a colleague's work). The rest is FastAPI and Pydantic doing their jobs. I'd rather have 18 tests I can justify than 80 that pad a number.
