# Build context: repo root (docker compose build context: .)
FROM python:3.12-slim AS builder

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY etl/requirements.txt .
RUN pip install --user -r requirements.txt


FROM python:3.12-slim

RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app
COPY --from=builder /root/.local /app/.local
COPY etl ./etl

ENV PATH=/app/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# data/ is bind-mounted at runtime (see docker-compose.yml), not baked into the image.
RUN mkdir -p /app/data && chown -R app:app /app
USER app

# One-shot job: loads data/employees.csv + data/telemetry_logs.jsonl into postgres.
CMD ["python", "-m", "etl.load_data"]
