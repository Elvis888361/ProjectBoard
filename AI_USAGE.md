# AI usage

Short version: **I used Claude (via Claude Code) heavily, for research, for scaffolding,
and for a lot of the first-draft code.** The brief says unexamined AI use is the problem,
not AI use — so this document is about what I did to make sure it was examined.

The three places it was genuinely wrong are in their own section below, because those are
the ones that say something useful.

---

## Tools

- **Claude (Claude Code)** — the main one. Research, first-draft implementation, tests.
- Nothing else. No Copilot, no Cursor.

---

## What I used it for

**Research, before I wrote any code.** This was the highest-value use and it changed the
design. I asked for evidence on what production board products actually use for realtime,
what breaks about Postgres `LISTEN/NOTIFY` at scale, and how Jira/Trello/Figma model card
ordering — with primary sources, not blog summaries. That's where the Linear/Asana/Figma
citations in ARCHITECTURE.md come from, along with the Recall.ai outage write-up, Joel
Jacobson's pgsql-hackers benchmark (9,126 → 238 TPS at 1,000 idle listeners), and the
Trello engineer's HN comment describing their float-position renumbering.

I want to be precise about what this changed, because it's the single most important thing
AI did on this project: **it talked me out of my own conclusion.** I went in intending to
argue "SSE is the smart modern choice." The research said the opposite — no named
production board uses SSE as its primary transport; they all use WebSockets. So I rewrote
the argument. The version in ARCHITECTURE.md now *concedes* the industry point and makes a
narrower, defensible claim instead: the hard part is the replay log, not the transport, and
every WebSocket team had to build that log by hand anyway. That's a better argument because
it's true, and I'd never have found it by reasoning from first principles in a vacuum.

**Scaffolding and first drafts.** FastAPI wiring, the Pydantic schemas, the React
components, the CSS, the docker-compose and GitHub Actions files. This is the boring 60%
and AI is straightforwardly good at it.

**The fractional-indexing algorithm.** I had it port David Greenspan's algorithm from the
JS reference implementation to Python. I did *not* trust the port — see below.

**Test scaffolding**, then I rewrote what the tests actually asserted (below).

---

## Where it was wrong, and how I caught it

These three are the reason I trust the rest of it.

### 1. The move endpoint had a genuine data-corruption bug, and a test caught it

The first draft of `move_task` treated "the client named no neighbours" as "this column is
empty" and generated the *first* position key. That's wrong: naming no neighbours means
**rank last**. The consequence is not cosmetic — every task moved into a column without
explicit neighbours got handed the same key `a0`, so two of them would collide and the
column's order would be decided by the id tie-break instead of by the user.

I found it because I'd written an integration test asserting a specific final order
(`["Top", "Dragged", "Bottom"]`), and it came back `["Top", "Bottom", "Dragged"]`. Fixed
by falling back to the column's last position, and the same branch now also handles a
neighbour that vanished mid-drag. The test is
`test_move_places_a_task_between_its_new_neighbours`.

**This is the one I'd want a reviewer to look at**, because it's the exact failure mode
AI-assisted code is supposed to have: plausible, confident, passes a superficial reading,
and silently wrong in a way only a test with a real assertion catches.

### 2. The SSE tests deadlocked, and the fix was to stop testing in-process

The first draft of the tests used `httpx.ASGITransport` — the standard, documented way to
test a FastAPI app. Against the SSE endpoint, it hung forever. Not failed. Hung.

The cause is structural, not a bug I could patch: `ASGITransport` awaits the ASGI
application *to completion* before returning a response, and an SSE stream by definition
never completes. **The in-process transport cannot test this endpoint, at all.**

So the tests now boot a real uvicorn server on a real socket (`conftest.py`). That's
fifteen extra lines and it means the three realtime tests exercise the actual HTTP stack,
the actual `LISTEN/NOTIFY` round trip, and the actual wire format. Better tests than I
would have written if the easy path had worked.

### 3. The nginx config broke the app in the browser (and the test suite couldn't see it)

The generated SSE config used `location /api/v1/projects/ { proxy_buffering off; … }`.
Two problems, neither of which any test would have caught:

- It matched **every** project endpoint, not just the event stream, disabling buffering
  for responses that want it.
- nginx 301-redirects the bare `/api/v1/projects` path when a trailing-slash prefix
  location like that exists — so the *project list*, the first thing the app loads,
  returned a redirect instead of data.

I only found it by running the built stack and curling through nginx rather than hitting
uvicorn directly. Fixed with a regex location that matches the stream and nothing else.
The lesson I'd draw: the tests were all green while the actual product was broken, because
every test bypassed the proxy. So CI now has a third job that runs `docker compose up` and
curls the real thing.

### Smaller corrections

- It reached for `python-jose` and `passlib`, which is what most FastAPI tutorials still
  show. Both are unmaintained; python-jose carries **CVE-2024-33663** (algorithm confusion
  → signature forgery) and passlib is broken outright by bcrypt 5.x. I checked the current
  FastAPI docs and switched to **PyJWT** and **pwdlib[argon2]**, which is what FastAPI
  itself now recommends. Worth knowing that the *popular* answer here is now the *insecure*
  answer.
- The `login` handler short-circuited on "no such user" without hashing. That's a timing
  oracle — a real Argon2 verify is ~50ms, skipping it is ~0 — so the endpoint would have
  leaked which emails have accounts even though both branches returned the same message. I
  added a dummy hash so both paths cost the same.
- The first draft happily let the SSE endpoint's pooled DB connection be held for the life
  of a stream. I restructured the generator to acquire and release around each read.

---

## What I checked myself, and how

**The ranking algorithm.** This is ported code, it's the one real algorithm in the
codebase, and its failure mode is silent (a subtly wrong key generator doesn't crash, it
quietly scrambles the order of everyone's board). So I did not take it on trust. I wrote
nine tests including a **seeded fuzz test** — 300 random inserts, then assert that sorting
by the generated keys still reproduces the list — and a test that 1000 appends keep the key
under 5 characters, which is the property the integer/fraction split exists to provide and
the one a naive implementation silently fails. I also read the algorithm until I could
explain *why* the integer part encodes its own length, which is in the module docstring.

**The realtime path, by hand, on the running stack.** Not just via tests: I brought up
`docker compose`, opened an SSE stream with `curl -N` as one user, made changes as another,
and watched the events arrive. Then I reconnected with `Last-Event-ID: 1` and confirmed the
server replayed *exactly* the one event I'd missed — and that a caught-up client replays
nothing. Then the same again through nginx, which is how I found bug #3.

**The `LISTEN/NOTIFY` limits.** I didn't want to assert "this scales fine" on faith, so the
specific numbers in ARCHITECTURE.md are ones I traced to primary sources — the Postgres
source comment about the commit lock, the pgsql-hackers benchmark thread, PgBouncer's
feature matrix saying `LISTEN | Never`. I also deliberately *dropped* a set of
widely-circulated "safe throughput" numbers after finding they originated from an HN
commenter who admitted generating them with ChatGPT. They're all over the web now as if
they were measured. They weren't.

**Everything else:** I ran it. 18 backend tests, 5 frontend tests, ruff, eslint, tsc, and a
clean `docker compose up --build` from an empty database.

---

## What I'd say if you asked "did you write this?"

I directed it, I made the architectural calls, I found and fixed the bugs above, and I can
explain any line in the repo — including *why* the position key has an integer part, why
`NOTIFY` carries an ID instead of a row, and why the version check is a 409 and not a 412.

The code itself was substantially drafted by Claude. That's the honest answer, and per the
brief it's the answer that's supposed to be fine. The part I'd defend as mine is the
judgement: what to build, what to cut, what to distrust, and what to go and verify.
