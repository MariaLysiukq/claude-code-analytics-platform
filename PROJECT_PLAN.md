# Project Plan — Claude Code Usage Analytics Platform

Internship test assignment: build an analytics platform over synthetic Claude Code
telemetry data. Full end-to-end solution (PostgreSQL + ETL + REST API + Streamlit
dashboard) launched via a single `docker compose up`, plus a committed, reproducible
AI-agent setup for interacting with the dataset.

## 1. Source material

- Assignment brief: `AI Internship Test Assignment 2026.docx`
- Data generator + docs: `claude_code_telemetry.tar (2)/generate_fake_data.py`,
  `claude_code_telemetry.tar (2)/README.md`
- Generated data: `claude_code_telemetry.tar (2)/output/employees.csv`,
  `claude_code_telemetry.tar (2)/output/telemetry_logs.jsonl`
  - Note: this directory is named `claude_code_telemetry.tar (2)` (likely a
    duplicate-download artifact), not `claude_code_telemetry`. To be renamed/moved
    into the repo proper during scaffolding.

## 2. Assignment requirements (confirmed understanding)

The brief asks for five things, evaluated with roughly equal weight — not just the
four originally discussed:

1. **Data Processing** — ingest, clean, and store the provided event data.
2. **Analytics & Insights** — extract meaningful patterns, metrics, trends.
3. **Dashboard/Visualization** — interactive dashboards for different personas.
4. **Agent Setup & Tuning** — a committed, reproducible agentic-tool configuration
   (skill, CLAUDE.md/rules, MCP server, subagent, hook, or slash command) that lets
   the agent query/analyze this specific dataset. Plain chat usage does not satisfy
   this. Must be committed to the repo with reproduction instructions.
5. **Technical Implementation** — end-to-end, single documented startup command
   (`docker compose up` or equivalent), documented architectural decisions, basic
   error handling and data validation.

Cross-cutting requirements:

- Never commit API keys/credentials; use env vars + `.env.example`.
- README with setup instructions and architectural overview.
- Must be able to explain the architecture, decisions, and problems hit —
  ownership of the solution is graded directly ("Understanding").
- Optional enhancements (not required): ML/anomaly detection, real-time streaming,
  advanced statistics, additional API endpoints for programmatic access.

## 3. Data shapes (confirmed understanding)

### Employees (`employees.csv`, 30 rows)

| column | notes |
|---|---|
| `email` | PK; matches `user.email` in telemetry |
| `full_name` | |
| `practice` | one of 5: Platform / Data / ML / Backend / Frontend Engineering |
| `level` | L1–L10, bell curve centered L4–L6 |
| `location` | one of 5 countries |

### Telemetry (`telemetry_logs.jsonl`, 8,970 lines / 57MB)

CloudWatch-style log batches, one JSON object per line:

```
{ messageType, owner, logGroup, logStream, subscriptionFilters,
  logEvents: [ { id, timestamp (epoch ms), message (JSON-encoded string) }, ... ],
  year, month, day }
```

Each `logEvents[].message`, once parsed, is:

```
{ body, attributes: { ...common..., ...event-specific... }, scope, resource }
```

Common `attributes` on every event: `event.timestamp`, `organization.id`,
`session.id`, `terminal.type`, `user.account_uuid`, `user.email`, `user.id`.

Common `resource`: `host.arch`, `host.name`, `os.type`, `os.version`,
`service.name`, `service.version`, `user.practice`, `user.profile`, `user.serial`.

Five event types (`body`):

| event | `body` | distinguishing attributes |
|---|---|---|
| user prompt | `claude_code.user_prompt` | `prompt` (`<REDACTED>`), `prompt_length` |
| API request | `claude_code.api_request` | `model`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_creation_tokens`, `cost_usd`, `duration_ms` |
| tool decision | `claude_code.tool_decision` | `tool_name`, `decision` (accept/reject), `source` |
| tool result | `claude_code.tool_result` | `tool_name`, `success`, `duration_ms`, `decision_source`, `decision_type`, optional `tool_result_size_bytes` |
| API error | `claude_code.api_error` | `error`, `status_code`, `model`, `attempt`, `duration_ms` |

**Known gotcha:** almost all numeric fields (`cost_usd`, `*_tokens`, `duration_ms`,
`attempt`, `prompt_length`) are serialized as **strings**, not JSON numbers — ETL
must cast explicitly. Sessions are implicit via `session.id`, not materialized
anywhere — must be derived.

## 4. Proposed architecture

### 4.1 PostgreSQL — two-layer model

- `raw_events` (JSONB, append-only landing zone): full-fidelity copy of every
  parsed event, keyed by the log event `id`. Preserves fields we haven't typed and
  allows reprocessing without re-reading the 57MB source file.
- Typed star-ish schema for fast analytics:
  - `dim_employees` (email PK, full_name, practice, level, location)
  - `dim_sessions` (session_id PK, user_email FK, start/end timestamps,
    terminal_type, os_type, host_name, derived turn/event counts)
  - `fact_api_requests`, `fact_tool_events` (decision+result reconciled per tool
    call where possible), `fact_user_prompts`, `fact_api_errors` — one table per
    event type, real numeric/boolean/timestamp types, FK'd to session and employee.
- Rationale: typed fact tables keep dashboard-style `GROUP BY` queries
  (cost by model/practice, tool success rate, etc.) fast and indexable, while
  `raw_events` is the safety net for fidelity/audit/replay.
- Indexes: btree on `session_id`, `user_email`, `timestamp` per fact table.
  No partitioning — dataset scale (tens of thousands of events) doesn't warrant it.
- Schema shipped as a plain SQL init script — Alembic/migrations tooling is
  overkill at this scope.

### 4.2 ETL pipeline (own container)

- Streams `telemetry_logs.jsonl` line by line (never loads the full 57MB into
  memory), double-parses the nested `message` JSON string, routes by `body` to
  per-event-type handlers, validates/casts fields via Pydantic models, bulk-loads
  via `COPY`/executemany.
- Idempotent: PK on event id, `ON CONFLICT DO NOTHING` — safe to re-run.
- Malformed rows are logged and skipped, not fatal (satisfies "basic error
  handling and data validation").
- Runs once as an init job: `depends_on postgres (service_healthy)`; api and
  dashboard `depends_on etl (service_completed_successfully)`.

### 4.3 REST API (FastAPI)

- Talks only to Postgres. The dashboard talks only to this API — clean
  separation, and the API is an explicit graded deliverable, not just a DB view.
- Raw resource endpoints: `/employees`, `/sessions`, `/events` (paginated,
  filterable).
- Aggregate analytics endpoints: `/analytics/cost-by-model`,
  `/analytics/cost-by-practice`, `/analytics/tool-reliability`,
  `/analytics/active-users`, `/analytics/error-rates`,
  `/analytics/session-stats` — aggregation done in SQL, not in the dashboard.
- `/health` endpoint for container healthcheck.

### 4.4 Streamlit dashboard

- Multi-page, targeting distinct personas per the brief's ask to "consider
  different user personas":
  - **Overview / FinOps** — cost & token trends over time.
  - **Engineering Manager** — usage broken down by practice/level.
  - **Platform** — tool adoption & reliability, error rates.
  - **Session Explorer** — drill-down into individual sessions.
- Fetches data from the REST API with `st.cache_data`, never queries Postgres
  directly.

### 4.5 Orchestration

- Single command: `docker compose up --build`.
- Service graph: `postgres` → `etl` (one-shot) → `api` → `dashboard`, wired with
  healthchecks / `depends_on` conditions for deterministic startup ordering.
- Secrets via `.env` (gitignored) + committed `.env.example`.

### 4.6 Agent setup deliverable

- A committed skill (or CLAUDE.md-driven equivalent) that teaches the agent this
  repo's schema, common query patterns against the fact tables, and how to
  produce analytical output from the dataset — reproducible from a fresh clone,
  not dependent on chat history.

## 5. Step-by-step execution plan

1. **Repo scaffolding** — move/rename telemetry source data into the repo
   (`data/` or similar), set up top-level structure (`etl/`, `api/`, `dashboard/`,
   `db/`, `.claude/` or equivalent for agent config), `.env.example`, `.gitignore`.
2. **Database schema** — write the SQL init script: `raw_events`, `dim_employees`,
   `dim_sessions`, `fact_api_requests`, `fact_tool_events`, `fact_user_prompts`,
   `fact_api_errors`, plus indexes.
3. **ETL pipeline** — implement streaming parse/validate/load for
   `employees.csv` and `telemetry_logs.jsonl`; Pydantic models per event type;
   session derivation logic; idempotent bulk load; error logging for malformed
   rows.
4. **REST API** — FastAPI app with SQLAlchemy models mirroring the schema,
   resource + analytics endpoints, `/health`, CORS for the dashboard.
5. **Streamlit dashboard** — multi-page app consuming the API, one page per
   persona, cached requests.
6. **Docker Compose** — Dockerfiles for etl/api/dashboard, `docker-compose.yml`
   wiring postgres/etl/api/dashboard with healthchecks and `depends_on`
   conditions; verify `docker compose up --build` is the single required command.
7. **Agent setup** — write the committed skill/CLAUDE.md that gives the agent
   schema knowledge and query patterns for this dataset; include reproduction
   instructions.
8. **Validation pass** — run the full stack from a clean state, sanity-check
   row counts and a few known aggregates (e.g. total simulated cost) against the
   generator's own summary output, exercise each dashboard page and API endpoint.
9. **Documentation** — top-level README (setup instructions + architectural
   overview + decisions/tradeoffs), LLM usage documentation, brief presentation
   of approach and findings per the submission checklist.

## 6. Open items / things to confirm before or during build

- Final decision on merging `tool_decision` + `tool_result` into one
  `fact_tool_events` row vs. keeping them separate (currently leaning toward
  merged, keyed by session_id + tool_name + adjacency in time).
- Exact directory layout and naming for the data source folder.
- Choice of agent-config mechanism (Claude Code skill vs. CLAUDE.md vs. MCP
  server) — currently leaning toward a Claude Code skill.
