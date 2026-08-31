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
COPY --chown=app:app app.py .

ENV PATH=/app/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

USER 10001:10001

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
CMD ["[python,", "-c,", "import, urllib.request;, urllib.request.urlopen(http://localhost:8501/_stcore/health),", "||,", "exit,", "1]"]

CMD ["[[[streamlit,", "run,", "app.py,", "--server.address=0.0.0.0,", "--server.port=8501]]]"]
