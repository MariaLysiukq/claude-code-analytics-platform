<p align="center">
    <h1 align="center">Claude Code Usage Analytics Platform</h1>
</p>

---

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.28+-FF4B4B.svg?logo=streamlit&logoColor=white)](https://streamlit.io)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15+-4169E1.svg?logo=postgresql&logoColor=white)](https://www.postgresql.org)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

## What is Claude Code Analytics?

An end-to-end cloud analytics platform for processing, analyzing, and visualizing Claude Code telemetry. It features a **managed PostgreSQL** storage layer (Neon.tech), a **FastAPI** backend hosted on Render, and a multi-persona **Streamlit dashboard** deployed on Streamlit Cloud. 

The project includes a memory-efficient streaming ETL pipeline for data ingestion and a pre-configured **Claude Code agent skill** for natural language SQL querying.

## Installation & Deployment

- **Cloud Infrastructure**: Deploy the FastAPI app (`api/`) to [Render](https://render.com) and the Dashboard (`dashboard/app.py`) to [Streamlit Cloud](https://share.streamlit.io). Use [Neon.tech](https://neon.tech) for the PostgreSQL database.
- **Local Setup**: Clone the repository and install dependencies using Poetry:
  ```bash
  poetry install

  ```

* **Data Generation**: Generate synthetic telemetry data locally (creates files in `output/`):
```bash
poetry run python generate_fake_data.py

```


* **Database Initialization & Load**: Initialize the schema and run the ETL pipeline to populate your Neon cloud database:
```bash
poetry run python -c "import psycopg2; from etl.config import DATABASE_URL; conn = psycopg2.connect(DATABASE_URL); conn.cursor().execute(open('db/init/01_schema.sql').read()); conn.commit();"
poetry run python -m etl.load_data

```



## Screenshots

Executive / Finance View <img width="1280" height="600" alt="зображення" src="https://github.com/user-attachments/assets/d3335499-c580-467c-9bd1-73cd90a89f28" />
Developer / Engineering View <img width="1280" height="600" alt="зображення" src="https://github.com/user-attachments/assets/d3335499-c580-467c-9bd1-73cd90a89f28" />

Analytics Dashboard
The Streamlit interface (`dashboard/app.py`) provides two tailored persona views:
* **Executive / Finance View**: Focuses on financial telemetry—total cost, daily spend trends, cost breakdown by engineering practice, and model efficiency.
* **Developer / Engineering View**: Focuses on system performance—token consumption metrics, tool execution acceptance vs. failure rates, API error rates, and HTTP status code distributions.

Features built-in date-range controls, client-side response caching (`st.cache_data`, 60s TTL), and retry options during API connection failures.

---

## AI Agent Integration

This repository includes a pre-committed Claude Code skill (`.claude/skills/telemetry-analytics/SKILL.md`). When opening this codebase inside Claude Code, you can execute natural language analytics queries directly:

> "Which tool has the highest execution failure rate?"
> "Show me the top 5 practice areas by API token usage over the last 7 days."

## Development and contributions

Code quality enforcement is managed via `pre-commit` hooks. We use **Ruff** for Python styling, **Mypy** for type checking, and **SQLFluff** for PostgreSQL dialect formatting.

To set up your local build environment and test contributions:

```bash
pip install pre-commit sqlfluff ruff mypy
pre-commit install
pre-commit run --all-files

```

## Architecture Overview

```text
                               ┌───────────────────────────┐
                               │   output/employees.csv    │
                               │ output/telemetry_logs.jsonl│
                               └─────────────┬─────────────┘
                                             │ (Streaming Ingestion)
                                             ▼
                               ┌───────────────────────────┐
                               │     etl (Local Script)    │
                               └─────────────┬─────────────┘
                                             │ (Idempotent Load)
                                             ▼
                               ┌───────────────────────────┐
                               │  Neon.tech (PostgreSQL)   │
                               └─────────────▲─────────────┘
                                             │ (SQL Aggregations)
                               ┌─────────────┴─────────────┐
                               │     Render (FastAPI)      │
                               └─────────────▲─────────────┘
                                             │ (HTTP JSON API)
                               ┌─────────────┴─────────────┐
                               │ Streamlit Cloud Dashboard │
                               └───────────────────────────┘

```

* **PostgreSQL (Neon.tech)**: Two-layer relational store combining a JSONB raw event landing zone with a fully typed star schema.


* **ETL**: One-shot, memory-efficient streaming pipeline using Pydantic validation and stateful tool decision/result event reconciliation. Run locally to populate the cloud database.


* **FastAPI Core (Render)**: Async REST service executing SQL aggregations directly on the database engine, strictly decoupling the UI from raw data.


* **Streamlit UI (Streamlit Cloud)**: Multi-view dashboard customized for Executive/Finance and Engineering personas.


* **Claude Agent Skill**: Native `.claude/skills/telemetry-analytics` integration for context-aware conversational analytics.



---

## Project Layout

```text
.
├── api/                    # FastAPI web service
│   ├── main.py             # Application entrypoint & lifespan management
│   ├── database.py         # Asyncpg connection pooling setup
│   ├── routers/            # Analytical query routing modules
│   ├── schemas/            # Pydantic response models
│   └── Dockerfile          # Multi-stage build with JSON exec notation
├── dashboard/              # Streamlit frontend application
│   ├── app.py              # Visual components and state handling
│   └── Dockerfile          # Security-hardened container spec
├── db/                     # Database initialization
│   └── init/
│       └── 01_schema.sql   # SQLFluff-compliant PostgreSQL schema definition
├── etl/                    # Ingestion pipeline logic
│   ├── load_data.py        # Streamed bulk ingestion execution engine
│   ├── parsing.py          # Line-by-line JSONL streaming parser
│   ├── models.py           # Data normalization & Pydantic models
│   ├── tool_reconciler.py  # Stateful decision/result event merger
│   └── config.py           # Configuration and environment variables
├── output/                 # Generated telemetry source data (local)
├── .claude/skills/         # Pre-committed Claude Code CLI analytical skills
├── .github/workflows/      # GitHub Actions CI automation
│   └── pre-commit.yml      # Linter & type-checking workflow
├── .hadolint.yaml          # Hadolint Dockerfile rule configurations
├── .sqlfluff               # SQLFluff PostgreSQL dialect rules
└── .pre-commit-config.yaml # Git hook definitions (Ruff, Mypy, SQLFluff, Hadolint)

```

## Database Schema & Architecture

Defined in `db/init/01_schema.sql` and formatted to adhere to strict PostgreSQL dialect rules.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                      Layer 1: Landing Zone                             │
├────────────────────────────────────────────────────────────────────────┤
│ raw_events (id PK, payload JSONB, session_id, user_email, timestamp)   │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Extracted & Normalized
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     Layer 2: Typed Star Schema                         │
├───────────────────────────────────┬────────────────────────────────────┤
│           DIMENSIONS              │               FACTS                │
├───────────────────────────────────┼────────────────────────────────────┤
│ dim_employees (email PK, ...)     │ fact_user_prompts                  │
│ dim_sessions (session_id PK, ...) │ fact_api_requests                  │
│                                   │ fact_tool_events (Reconciled)      │
│                                   │ fact_api_errors                    │
└───────────────────────────────────┴────────────────────────────────────┘

```

* **Layer 1 (Landing Zone)**: `raw_events` stores complete JSONB log payloads alongside promoted filter columns (`body`, `session_id`, `user_email`, `event_timestamp`), indexed via GIN.


* **Layer 2 (Star Schema)**:
* `dim_employees`: Organizational data (`email`, `full_name`, `practice`, `level`, `location`).


* `dim_sessions`: Session metadata derived by grouping events on `session.id`.


* `fact_user_prompts`: User prompt counts and lengths.


* `fact_api_requests`: LLM invocations, token usage split (input, output, cache read/creation), cost, and latency.


* `fact_tool_events`: Single-row representation combining matched `tool_decision` and `tool_result` events.


* `fact_api_errors`: API error details, HTTP status codes, and retry counts.





## ETL Pipeline

Located in `etl/load_data.py`:

* **Two-Pass Streaming:** Streams JSONL log files line-by-line to minimize memory footprint.


* *Pass 1*: Derives and loads `dim_sessions` (required as a Foreign Key target).


* *Pass 2*: Populates `raw_events` and all `fact_*` tables.




* **Sanitization & Parsing:** Pydantic models convert stringified numbers (e.g., `"cost_usd": "0.093"`) to floating point values and map literal `"undefined"` strings to SQL `NULL` values.


* **Tool Reconciliation:** Matches decision events (`tool_decision`) with execution result events (`tool_result`) into single rows inside `fact_tool_events`.


* **Bulk Idempotent Writes:** Uses PostgreSQL `ON CONFLICT` execution via `psycopg2.extras.execute_values` in buffered batches (`ETL_BATCH_SIZE=2000`).



---

## REST API Reference

The FastAPI web service executes aggregate calculations in PostgreSQL rather than application memory.

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/api/v1/health` | System and DB connectivity probe (returns `200` or `503`). |
| `GET` | `/api/v1/analytics/cost-by-model` | Spend, token breakdown, and latency metrics grouped by LLM model. |
| `GET` | `/api/v1/analytics/cost-by-practice` | Session count, token volume, and financial spend by practice. |
| `GET` | `/api/v1/analytics/cost-by-day` | Daily spend and volume timeseries data. |
| `GET` | `/api/v1/analytics/tool-reliability` | Per-tool acceptance rate, success rate, and duration statistics. |
| `GET` | `/api/v1/analytics/active-users` | Daily Active Users (DAU) and total active session counts. |
| `GET` | `/api/v1/analytics/error-rates` | API failure rates and error category breakdowns. |
| `GET` | `/api/v1/analytics/status-codes` | HTTP status code distributions across API request failures. |
| `GET` | `/api/v1/analytics/session-stats` | Fleet-wide average and median session shapes. |
> All analytics endpoints support temporal filtering via optional ISO-8601 query parameters: `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`.
>
>

---

## Configuration

All application configurations are managed via environment variables defined in `.env`:

* `DATABASE_URL`: PostgreSQL connection string (Neon.tech)
* `API_URL`: FastAPI backend URL (used by Streamlit Cloud)
* `ETL_DATA_DIR`: Directory containing source files (e.g., `output`)

