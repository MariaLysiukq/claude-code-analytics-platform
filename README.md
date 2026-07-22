# Claude Code Usage Analytics Platform

An end-to-end analytics platform over synthetic Claude Code CLI telemetry:
PostgreSQL + a streaming ETL pipeline + a FastAPI analytics service + a
multi-persona Streamlit dashboard, all launched with a single
`docker compose up --build`. Includes a committed Claude Code skill so an
agent can query and analyze the dataset directly, reproducibly, from a fresh
clone.

## Contents

- [Architecture](#architecture)
- [Quick start](#quick-start)
- [Project layout](#project-layout)
- [Database schema](#database-schema)
- [ETL pipeline](#etl-pipeline)
- [REST API](#rest-api)
- [Dashboard](#dashboard)
- [Agent setup — querying the dataset with Claude Code](#agent-setup--querying-the-dataset-with-claude-code)
- [Configuration](#configuration)
- [Design decisions & tradeoffs](#design-decisions--tradeoffs)
- [Known limitations](#known-limitations)

## Architecture

```
data/employees.csv ─┐
                     ├─▶  etl (one-shot)  ─▶  postgres  ◀─  api (FastAPI)  ◀─  dashboard (Streamlit)
data/telemetry_logs.jsonl ─┘
```

- **postgres** — single source of truth. A two-layer schema: an append-only
  `raw_events` JSONB landing zone, plus a typed star-ish schema
  (`dim_employees`, `dim_sessions`, `fact_*`) for fast aggregation.
- **etl** — a one-shot container that streams the ~57MB `telemetry_logs.jsonl`
  line-by-line, validates/casts every field with Pydantic, derives sessions
  (not materialized in the source data), and idempotently loads Postgres.
  Runs once per `docker compose up` after Postgres reports healthy, and the
  `api` container waits for it to complete successfully.
- **api** — FastAPI service, the *only* thing that talks to Postgres besides
  the ETL job. Exposes a `/health` check and a set of `/analytics/*`
  aggregation endpoints; all `GROUP BY`/aggregation work happens in SQL, not
  in application code.
- **dashboard** — a Streamlit app that talks only to the API (never
  Postgres directly), with two persona views (Executive/Finance,
  Developer/Engineering) and a shared date-range filter.
- **.claude/skills/telemetry-analytics** — a Claude Code skill that teaches
  an agent this schema and a SQL query cookbook, so the dataset can be
  analyzed conversationally without re-deriving context each time.

Startup ordering is enforced with Compose `depends_on` conditions
(`service_healthy` / `service_completed_successfully`), so the single
`docker compose up --build` command is deterministic — no manual step
ordering required.

## Quick start

Requires Docker and Docker Compose.

```bash
cp .env.example .env      # adjust credentials if desired; .env is gitignored
docker compose up --build
```

This will, in order: start Postgres and wait for it to be healthy, run the
ETL job once to load `data/employees.csv` and `data/telemetry_logs.jsonl`,
then start the API and dashboard.

Once it's up:

| Service | URL |
|---|---|
| Dashboard | http://localhost:8501 |
| API | http://localhost:8000/api/v1 |
| API health | http://localhost:8000/api/v1/health |
| Postgres | `localhost:5432` (see `.env` for credentials) |

To reload data after a change (e.g. regenerating the source dataset), the
load is idempotent and safe to re-run:

```bash
docker compose run --rm etl python -m etl.load_data           # upsert
docker compose run --rm etl python -m etl.load_data --truncate # full reset
```

## Project layout

```
data/            synthetic source dataset (employees.csv, telemetry_logs.jsonl)
                 + generate_fake_data.py, the generator that produced it
db/init/         Postgres schema (01_schema.sql), run automatically on first boot
etl/             streaming ETL: parsing, Pydantic models, tool-event reconciliation, loader
api/             FastAPI service: config, connection pool, routers, response schemas
dashboard/       Streamlit app (single file, two persona views)
.claude/skills/  telemetry-analytics: agent skill for querying this dataset
docker-compose.yml
PROJECT_PLAN.md  detailed design notes and rationale behind the choices below
```

## Database schema

Defined in `db/init/01_schema.sql`, applied automatically on first Postgres
boot via the standard `/docker-entrypoint-initdb.d` mechanism.

**Layer 1 — landing zone**

- `raw_events` — one row per source log event (`id` PK), full-fidelity JSONB
  `payload` plus a few promoted columns (`body`, `session_id`, `user_email`,
  `event_timestamp`) for filtering without unpacking JSON. Exists so the
  57MB source file never needs to be re-read to recover a field the typed
  tables didn't promote.

**Layer 2 — typed star schema**

- `dim_employees(email PK, full_name, practice, level, location)`
- `dim_sessions(session_id PK, user_email FK, organization_id, terminal_type, os_type, os_version, host_name, host_arch, started_at, ended_at, event_count, prompt_count)` — sessions are derived by the ETL (not materialized in the source) by grouping events on `session.id`.
- `fact_user_prompts(id, session_id FK, user_email FK, event_timestamp, prompt_length)`
- `fact_api_requests(id, session_id FK, user_email FK, event_timestamp, model, input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd, duration_ms)`
- `fact_tool_events(id, session_id FK, user_email FK, tool_name, decision_event_id, decision, decision_source, decision_timestamp, result_event_id, success, decision_type, tool_result_size_bytes, duration_ms, result_timestamp)` — `tool_decision` and `tool_result` source events reconciled into one row per tool call (see [ETL pipeline](#etl-pipeline)).
- `fact_api_errors(id, session_id FK, user_email FK, event_timestamp, model, error, status_code, attempt, duration_ms)`

All fact tables index `session_id`, `user_email`, and their timestamp column;
`raw_events` additionally has a GIN index on `payload` for ad-hoc JSONB
queries. No partitioning or migration tooling — the dataset (tens of
thousands of events) doesn't warrant either, and a plain SQL init script is
simpler to audit than a migrations framework at this scale.

## ETL pipeline

`etl/load_data.py`, run via `python -m etl.load_data` (the ETL container's
default command).

- **Streaming, two passes.** `etl/parsing.py` streams `telemetry_logs.jsonl`
  line by line — a batch is one JSON line containing `logEvents[]`, and each
  `logEvents[].message` is itself a JSON-encoded string requiring a second
  parse. Pass 1 derives `dim_sessions` (a FK target for every fact table, so
  sessions must exist before fact rows are inserted); pass 2 streams the file
  again to populate `raw_events` and the fact tables. The file is never
  loaded fully into memory.
- **Validation.** Every event's `attributes` are parsed through a Pydantic
  model (`etl/models.py`) before being cast into typed columns. The source
  data serializes almost all numeric fields as **strings** (`"cost_usd":
  "0.093..."`) and sometimes uses the literal string `"undefined"` as a
  stand-in for null — the models normalize both. A row that fails validation
  is logged and skipped (not fatal), satisfying basic error-handling/data
  validation without aborting the whole load; a final summary reports rows
  sent vs. skipped per table.
- **Tool event reconciliation.** `tool_decision` and `tool_result` are
  separate source events but describe one tool call. `etl/tool_reconciler.py`
  tracks at most one "open" decision per session (per the generator's actual
  emission order — a decision is followed by its result iff `accept`; a
  `reject` never gets a result), merging matched pairs into a single
  `fact_tool_events` row and flushing unmatched decisions decision-only.
- **Idempotent.** Every insert uses `ON CONFLICT` (`DO NOTHING` for
  append-only facts, `DO UPDATE` for `dim_employees`/`dim_sessions`/
  `fact_tool_events`, which can legitimately be revised). Safe to re-run
  against already-loaded data; `--truncate` forces a clean full reload.
- Buffered batch inserts (`ETL_BATCH_SIZE`, default 2000 rows) via
  `execute_values` rather than row-at-a-time inserts.

## REST API

FastAPI app (`api/main.py`), served at `/api/v1`, backed by an `asyncpg`
connection pool shared across requests via app lifespan state
(`api/database.py`). All aggregation is done in SQL (`api/routers/metrics.py`)
— the API only shapes rows into Pydantic response models
(`api/schemas/metrics.py`).

| Endpoint | Returns |
|---|---|
| `GET /api/v1/health` | `{status, database}`; 503 if the DB check fails. Used as the container healthcheck. |
| `GET /api/v1/analytics/cost-by-model` | Requests, tokens, total/avg cost, avg duration — grouped by model |
| `GET /api/v1/analytics/cost-by-practice` | Sessions, requests, tokens, cost — grouped by employee practice |
| `GET /api/v1/analytics/cost-by-day` | Daily request count, tokens, cost — for a spend trend line |
| `GET /api/v1/analytics/tool-reliability` | Per-tool acceptance rate and success rate, avg duration |
| `GET /api/v1/analytics/active-users` | Daily distinct active users and session count |
| `GET /api/v1/analytics/error-rates` | Overall error rate plus a breakdown by error type |
| `GET /api/v1/analytics/status-codes` | HTTP status code distribution across API errors |
| `GET /api/v1/analytics/session-stats` | Fleet-wide avg/median session duration, event/prompt counts, cost, tokens |

Every `/analytics/*` endpoint accepts optional `start_date` / `end_date`
query params (ISO-8601; inclusive lower bound, exclusive upper bound).

## Dashboard

Single-file Streamlit app (`dashboard/app.py`) that talks only to the REST
API — never queries Postgres directly, keeping the API as the one enforced
data-access boundary. Two persona views, selectable from the sidebar:

- **Executive / Finance** — total spend, request volume, avg cost/request,
  historical cost trend, and cost broken down by practice and by model.
- **Developer / Engineering** — token consumption by model/type, tool
  execution success rates, API error rate and breakdown, HTTP status code
  distribution.

A sidebar date-range filter applies across whichever view is active. API
calls are cached (`st.cache_data`, 60s TTL) and retried with backoff; if the
API is genuinely unreachable, the affected panel shows a warning instead of
crashing the page, and a "Retry / refresh data" button clears the cache.

## Agent setup — querying the dataset with Claude Code

`.claude/skills/telemetry-analytics/SKILL.md` is a committed Claude Code
skill that gives an agent working in this repo the schema knowledge and SQL
query patterns needed to analyze the dataset directly — reproducible from a
fresh clone, with no dependency on prior conversation history.

It documents:

- how to reach the data (`docker compose exec postgres psql ...` for ad-hoc
  SQL, or the REST API for anything already aggregated there);
- the full two-layer schema, table by table;
- a query cookbook (total/by-model/by-practice spend, top spenders, tool
  reliability, error breakdowns, session shape, daily active users);
- the source-data gotchas that matter for correct analysis (numeric fields
  as strings in raw JSONB, nullable `user_email`/`decision`/`success` fields
  that must be filtered before computing rates).

To use it: open this repo in Claude Code and ask an analytical question
about the dataset (e.g. "which tool has the worst acceptance rate?" or "what's
total spend by practice last week?") — the skill is picked up automatically
based on its description. It assumes the stack is already running
(`docker compose up --build`).

## Configuration

All configuration is via environment variables, sourced from a single `.env`
(gitignored; see `.env.example` for the template — no credentials are
committed). Key variables:

| Variable | Default | Used by |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `analytics` / `changeme` / `claude_code_analytics` | postgres, etl, api |
| `POSTGRES_PORT` | `5432` | host port mapping |
| `DATABASE_URL` | derived from the above | etl (psycopg2 DSN) |
| `API_PORT` | `8000` | host port mapping |
| `ETL_BATCH_SIZE` | `2000` | etl, rows per batch insert |
| `ETL_LOG_EVERY_N_LINES` | `1000` | etl, progress log frequency |

## Design decisions & tradeoffs

- **Two-layer schema over a single typed schema.** Keeping `raw_events`
  alongside the typed facts costs storage but means a field the typed models
  didn't anticipate is never lost — it can be promoted to a new column later
  without re-reading the source file. See `PROJECT_PLAN.md` §4.1.
- **API as a mandatory hop, not a convenience.** The dashboard could have
  queried Postgres directly; forcing it through the API keeps the API an
  independently useful, independently testable deliverable rather than a
  thin pass-through, and matches the assignment's explicit ask for
  programmatic access.
- **Tool events merged into one row per call.** `tool_decision` and
  `tool_result` are separate source events; reconciling them at load time
  (rather than joining at query time) makes "tool success rate" a single
  `GROUP BY` instead of a session-and-time-adjacency join on every query.
- **Plain SQL init script, no migrations framework.** At this scale
  (thousands of events, a fixed one-time schema), Alembic-style migrations
  add process overhead without a corresponding benefit.

## Known limitations

- The dataset is synthetic (see `data/SOURCE_README.md` /
  `data/generate_fake_data.py`) — absolute numbers are illustrative, not
  real usage.
- `fact_tool_events` reconciliation assumes at most one "open" tool decision
  per session at a time, matching the current generator's emission order; a
  source generator that interleaves concurrent tool calls within a session
  would need a more sophisticated matching strategy.
- No authentication on the API or dashboard — acceptable for a local/
  containerized evaluation environment, not for exposing beyond localhost.
