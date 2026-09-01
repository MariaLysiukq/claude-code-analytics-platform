# Build context: ./dashboard
FROM python:3.12-slim AS builder

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

COPY requirements.txt .
RUN pip install --user -r requirements.txt

FROM python:3.12-slim

RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app

WORKDIR /app

COPY --chown=app:app --from=builder /root/.local /app/.local
COPY --chown=app:app . .

ENV PATH=/app/.local/bin:$PATH \
    PYTHONPATH=/app/.local/lib/python3.12/site-packages:$PYTHONPATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER app

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
