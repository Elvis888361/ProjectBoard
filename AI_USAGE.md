# AI usage

I used **Claude (via Claude Code)** heavily — research, scaffolding, and a lot of the
first-draft code. Nothing else: no Copilot, no Cursor.

The brief says the problem is *unexamined* AI use, so this is about what I did to examine
it. The three places it was wrong are the interesting part, so they go first.

## Where it was wrong

**1. The move endpoint had a data-corruption bug.**

The first draft treated "the client named no neighbours" as "this column is empty" and
generated the *first* position key. It means rank **last**. So every task moved into a
column without explicit neighbours got handed the same key, `a0`, and they'd collide — the
column's order decided by an id tie-break instead of by the user. Silent order corruption.

I found it because an integration test asserted a specific final order and got
`["Top", "Bottom", "Dragged"]` instead of `["Top", "Dragged", "Bottom"]`.

This is the one I'd point a reviewer at, because it's exactly the failure mode AI code has:
plausible, confident, passes a read-through, and quietly wrong in a way only a test with a
real assertion catches.

**2. The SSE tests deadlocked, and the fix was to stop testing in-process.**

The first draft used `httpx.ASGITransport` — the standard, documented way to test FastAPI.
Against the SSE endpoint it hung forever. Not failed. Hung.

The cause is structural: `ASGITransport` awaits the ASGI app *to completion* before
returning a response, and an SSE stream never completes. The in-process transport cannot
test that endpoint at all. So the tests now boot a real uvicorn server on a real socket.
Fifteen extra lines, and the three realtime tests exercise the actual HTTP stack, the actual
`LISTEN/NOTIFY` round trip, and the actual wire format. Better tests than I'd have written
if the easy path had worked.

**3. The nginx config broke the app in the browser, and every test stayed green.**

The generated SSE block used `location /api/v1/projects/`. That matched every project
endpoint, not just the stream — and nginx 301-redirects the bare `/api/v1/projects` path
when a trailing-slash prefix location like that exists. So the project list, the first thing
the app loads, returned a redirect instead of data.

Nothing caught it, because every test bypassed the proxy. I only found it by running the
built stack and curling *through* nginx. Fixed with a regex location that matches the stream
and nothing else, and CI now has a third job that does `docker compose up` and curls the real
thing.

**Smaller ones.** It reached for `python-jose` and `passlib`, which is what most FastAPI
tutorials still show — both unmaintained, and python-jose carries CVE-2024-33663 (algorithm
confusion → signature forgery). I checked the current FastAPI docs and switched to PyJWT and
pwdlib/Argon2. Worth knowing that the popular answer there is now the insecure one. It also
short-circuited `login()` when the user didn't exist, which is a timing oracle — a real Argon2
verify is ~50ms and skipping it is ~0, so the endpoint leaked which emails have accounts even
though both branches returned the same message. Added a dummy hash.

## What it got right, and changed my mind about

The highest-value use was research, before I wrote any code. I asked what production board
products actually use for realtime, with primary sources.

The answer went against my instinct. I went in wanting to argue "SSE is the smart modern
choice." The evidence said no named production board uses SSE as its primary transport — they
all use WebSockets. So I rewrote the argument. ARCHITECTURE.md now concedes that outright and
makes a narrower claim instead: the hard part is the replay log, not the transport, and every
one of those teams had to build that log by hand anyway.

That's a better argument because it's true, and I wouldn't have found it reasoning from first
principles in a vacuum.

## What I verified myself

**The ranking algorithm.** It's ported code, it's the only real algorithm in the repo, and its
failure mode is silent. So I didn't take it on trust: nine tests, including a seeded fuzz test
that does 300 random inserts and asserts the sort order still reproduces the list, and a test
that 1000 appends keep the key under five characters — the property the integer/fraction split
exists to provide, and the one a naive implementation silently fails.

**The realtime path, by hand.** Brought up compose, opened a stream with `curl -N` as one user,
made changes as another, watched the events arrive. Reconnected with `Last-Event-ID: 1` and
confirmed the server replayed exactly the one event I'd missed, and that a caught-up client
replays nothing. Then the same through nginx, which is how I found bug 3.

**The `LISTEN/NOTIFY` limits.** The numbers in ARCHITECTURE.md are traced to primary sources —
the Postgres source comment about the commit lock, the pgsql-hackers benchmark, PgBouncer's
feature matrix. I also *dropped* a set of widely-quoted "safe throughput" figures after finding
they originated from an HN commenter who admitted generating them with ChatGPT. They're all over
the web now as if they were measured.

## The honest summary

The code was substantially drafted by Claude. I directed it, made the architectural calls, found
and fixed the bugs above, and can explain what's in the repo — why the position key has an
integer part, why `NOTIFY` carries an id instead of a row, why the version check is a 409 and
not a 412.

The part I'd defend as mine is the judgement: what to build, what to cut, what to distrust, and
what to go and verify.
