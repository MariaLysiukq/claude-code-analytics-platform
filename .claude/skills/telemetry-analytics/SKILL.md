---
name: telemetry-analytics
description: Use when asked to analyze, query, or extract insights from this repo's Claude Code usage telemetry dataset — cost/token spend, tool reliability, error rates, session shape, or per-employee/practice breakdowns. Teaches the two-layer Postgres schema, a SQL query cookbook, and how to reach the running stack (psql or the REST API) for ad-hoc analysis. Reproducible from a fresh clone; does not depend on prior chat history.
---

# Claude Code Analytics — dataset query skill

This repo ingests synthetic Claude Code CLI telemetry (`data/telemetry_logs.jsonl`,
`data/employees.csv`) into Postgres and serves it through a FastAPI layer and a
Streamlit dashboard. Use this skill whenever the task is to answer a question
*about the data itself* (spend, usage, reliability, trends) rather than to
change the application code.

Full architectural rationale lives in `PROJECT_PLAN.md` — read it if you need
the "why", not just the "how".

## 1. Getting access to the data

The stack must be running first:

```bash
docker compose up --build          # postgres -> etl (one-shot load) -> api -> dashboard
```

Two ways to query, pick based on the question:

- **One-off / exploratory SQL** — go straight to Postgres:
  ```bash
  docker compose exec postgres psql -U "${POSTGRES_USER:-analytics}" -d "${POSTGRES_DB:-claude_code_analytics}"
  ```
  (Credentials come from `.env`; defaults above match `.env.example`.)
- **Anything the dashboard already aggregates** — prefer the REST API over
  re-deriving the query yourself:
  ```bash
  curl "http://localhost:8000/api/v1/analytics/cost-by-model"
  ```
  All `/api/v1/analytics/*` endpoints accept optional `start_date`/`end_date`
  ISO-8601 query params (inclusive/exclusive respectively). See
  `api/routers/metrics.py` for the full endpoint list and exact SQL behind each.

Re-running the ETL after data changes is idempotent (`ON CONFLICT`-based
upserts): `docker compose run --rm etl python -m etl.load_data`. Add
`--truncate` for a full clean reload.

## 2. Schema reference

Two layers (see `db/init/01_schema.sql` for the authoritative DDL):

**Layer 1 — landing zone**
- `raw_events (id, body, session_id, user_email, event_timestamp, payload JSONB, ingested_at)`
  — one row per source log event, full fidelity. `body` is the event type
  (`claude_code.user_prompt`, `.api_request`, `.tool_decision`, `.tool_result`,
  `.api_error`). Use this when a field you need isn't in the typed tables —
  everything from the original event is in `payload`.

**Layer 2 — typed star schema (query this first)**
- `dim_employees (email PK, full_name, practice, level, location)` —
  `practice` ∈ {Platform, Data, ML, Backend, Frontend Engineering}; `level` is
  an integer 1–10.
- `dim_sessions (session_id PK, user_email FK, organization_id, terminal_type,
  os_type, os_version, host_name, host_arch, started_at, ended_at, event_count,
  prompt_count)` — one row per derived session (sessions aren't materialized in
  the source; the ETL builds this from `session.id` on every event).
- `fact_user_prompts (id, session_id FK, user_email FK, event_timestamp, prompt_length)`
- `fact_api_requests (id, session_id FK, user_email FK, event_timestamp, model,
  input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
  cost_usd NUMERIC, duration_ms)` — the spend/token source of truth.
- `fact_tool_events (id, session_id FK, user_email FK, tool_name,
  decision_event_id, decision, decision_source, decision_timestamp,
  result_event_id, success, decision_type, tool_result_size_bytes, duration_ms,
  result_timestamp)` — `tool_decision` + `tool_result` reconciled into one row
  per tool call where the ETL could match them (see
  `etl/tool_reconciler.py`); rejected calls have no `result_*` fields.
- `fact_api_errors (id, session_id FK, user_email FK, event_timestamp, model,
  error, status_code, attempt, duration_ms)`

All fact tables are indexed on `session_id`, `user_email`, and
`event_timestamp` (or the closest equivalent) — filter/join on those freely.

## 3. Query cookbook

Total simulated spend and request count:
```sql
SELECT COUNT(*) AS requests, SUM(cost_usd) AS total_cost_usd
FROM fact_api_requests;
```

Spend and tokens by model:
```sql
SELECT model, COUNT(*) AS requests,
       SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens,
       SUM(cost_usd) AS total_cost_usd
FROM fact_api_requests
GROUP BY model ORDER BY total_cost_usd DESC;
```

Spend by engineering practice (joins in employee dimension):
```sql
SELECT e.practice, COUNT(DISTINCT r.session_id) AS sessions,
       SUM(r.cost_usd) AS total_cost_usd
FROM fact_api_requests r
LEFT JOIN dim_employees e ON e.email = r.user_email
GROUP BY e.practice ORDER BY total_cost_usd DESC;
```

Top spenders (individual employees):
```sql
SELECT user_email, SUM(cost_usd) AS total_cost_usd, COUNT(*) AS requests
FROM fact_api_requests
WHERE user_email IS NOT NULL
GROUP BY user_email ORDER BY total_cost_usd DESC LIMIT 10;
```

Tool acceptance and success rates:
```sql
SELECT tool_name,
       COUNT(*) FILTER (WHERE decision = 'accept')::float
         / NULLIF(COUNT(*) FILTER (WHERE decision IS NOT NULL), 0) AS acceptance_rate,
       COUNT(*) FILTER (WHERE success)::float
         / NULLIF(COUNT(*) FILTER (WHERE success IS NOT NULL), 0) AS success_rate
FROM fact_tool_events
GROUP BY tool_name ORDER BY acceptance_rate ASC;
```

API error rate and breakdown:
```sql
SELECT error, COUNT(*) AS occurrences, COUNT(DISTINCT session_id) AS sessions_hit
FROM fact_api_errors
GROUP BY error ORDER BY occurrences DESC;
```

Session shape (duration, size):
```sql
SELECT AVG(EXTRACT(EPOCH FROM (ended_at - started_at))) AS avg_duration_s,
       AVG(event_count) AS avg_events, AVG(prompt_count) AS avg_prompts
FROM dim_sessions;
```

Daily active users / usage trend:
```sql
SELECT date_trunc('day', started_at)::date AS day,
       COUNT(DISTINCT user_email) AS active_users, COUNT(*) AS sessions
FROM dim_sessions
GROUP BY 1 ORDER BY 1;
```

Reaching into a `raw_events` payload for a field not yet typed (e.g. redacted
prompt text's length distribution, or a resource attribute not promoted to a
fact table):
```sql
SELECT payload -> 'attributes' ->> 'some_field'
FROM raw_events
WHERE body = 'claude_code.user_prompt'
LIMIT 20;
```

## 4. Gotchas to carry into analysis

- Numeric-looking source fields (`cost_usd`, `*_tokens`, `duration_ms`,
  `attempt`, `prompt_length`) arrive as **strings** in the raw JSONL; already
  cast to real numeric types in the Layer 2 tables (see `etl/models.py`) —
  no re-casting needed when querying `fact_*`, only when reading
  `raw_events.payload` directly.
- `user_email` can be `NULL` on fact rows: either the event had no email or it
  referenced an email not present in `dim_employees` (ETL nulls it rather than
  dropping the row — logged as a warning during load).
- `fact_tool_events.success` / `decision` can both be `NULL` — always
  `FILTER (WHERE decision IS NOT NULL)` etc. before computing a rate, or you'll
  silently under-count the denominator.
- Prefer the REST API's `/analytics/*` endpoints for anything already exposed
  there (they encode the correct `NULL`-safe aggregation) — hand-roll SQL only
  for questions the API doesn't already answer.
