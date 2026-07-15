# AI usage

I used Claude for two things: research, and as a second pair of eyes on bugs and early architecture decisions. Everything below is a case where I caught or verified the problem myself — Claude helped me trace or confirm it.

The brief asks what I used it for and, more importantly, what I checked myself. So here's the honest version, starting with the bugs it helped me fix, because that's the useful part.

## Bugs it helped me fix

**The move endpoint corrupted card order.** My first pass treated "no neighbours given" as "empty column" and handed out the first position key — but it should mean rank *last*. So two cards moved into the same column both got key `a0` and collided. An API test that checked the final order caught it (`["Top","Bottom","Dragged"]` instead of `["Top","Dragged","Bottom"]`), and Claude helped me trace why. This is the one I'd show a reviewer — looks right, reads right, quietly wrong until a real assertion hits it.

**The SSE tests hung forever.** I'd tested with httpx's in-process transport, which is the normal way. It can't test SSE — it waits for the response to finish, and a stream never finishes. Claude pointed me at booting a real server on a real socket instead. The realtime tests now go through the actual HTTP + LISTEN/NOTIFY path, which is better anyway.

**The nginx config broke the app but all tests passed.** My SSE block matched every project route, not just the stream, and nginx started 301-redirecting the project list — the first thing the app loads. No test caught it because they all skipped the proxy. I found it by running the built stack and curling through nginx. CI now has a job that does `docker compose up` and checks the app actually comes up.

**Two smaller ones.** I'd reached for `python-jose` and `passlib`  — Claude flagged both as unmaintained, and that python-jose has a known CVE. Switched to PyJWT and Argon2. It also caught that my login code skipped hashing when the email didn't exist, which leaks which emails have accounts through timing — added a dummy hash so both paths take the same time.

## Summary

I wrote the code. Claude helped with research and helped me find and fix the bugs above. I made the design calls and can explain any part of it — why the position key is built the way it is, why NOTIFY carries an id and not the row, why a stale write is a 409 and not a 412. The judgement is mine: what to build, what to cut, what to distrust, what to go and verify.