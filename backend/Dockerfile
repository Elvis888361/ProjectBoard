FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations

RUN pip install --no-cache-dir -e ".[dev]"

EXPOSE 8000

# One worker. N>1 works (NOTIFY carries events between them), but at this scale one is
# plenty and it makes the in-memory rate limiter actually correct.
#
# The graceful-shutdown bound matters: an SSE stream never completes, so uvicorn would
# otherwise wait forever on SIGTERM. Cut them; EventSource reconnects and replays.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--timeout-graceful-shutdown", "5"]
