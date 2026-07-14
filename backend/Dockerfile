FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

# One worker, on purpose.
#
# The SSE fan-out is in-process: the LISTEN connection in this worker pushes to the
# subscriber queues in this worker. Postgres NOTIFY is what carries an event ACROSS
# workers, so this is already correct for N>1 -- each worker holds its own listener and
# serves its own subscribers. I'm running one because at tens of users one process is
# more than enough, and because a single worker makes the in-memory login rate limiter
# actually correct rather than approximately correct.
#
# `--timeout-graceful-shutdown 5`: an SSE stream never completes on its own, so without
# a bound uvicorn waits forever for it to finish on SIGTERM. Five seconds, then cut
# them; EventSource reconnects on its own and replays from Last-Event-ID.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "5"]
