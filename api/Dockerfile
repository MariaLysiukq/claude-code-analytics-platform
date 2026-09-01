# Build context: repo root (docker compose build context: .)
FROM python:3.12-slim AS builder

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY api/requirements.txt .
RUN pip install --user -r requirements.txt


FROM python:3.12-slim

RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app
COPY --from=builder /root/.local /app/.local
COPY api ./api

ENV PATH=/app/.local/bin:$PATH \
    PYTHONPATH=/app/.local/lib/python3.12/site-packages:$PYTHONPATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN chown -R app:app /app
USER app

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
