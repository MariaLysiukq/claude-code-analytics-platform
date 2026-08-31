# Claude Code Project Guidelines — Analytics Platform

## Operational Commands
- **Launch Full Stack**: `docker compose up --build`
- **Run API Unit Tests**: `pytest` or `docker compose exec api pytest`
- **Re-run ETL Data Sync**: `docker compose run --rm etl python -m etl.load_data`
- **Reset & Re-run ETL Data Sync**: `docker compose run --rm etl python -m etl.load_data --truncate`
- **Lint & Format**: `ruff check .` / `ruff format .`

## Architecture & Code Boundaries
- **Layer 1 (Landing)**: `raw_events` stores unparsed JSONB logs; do not alter raw schema[cite: 2].
- **Layer 2 (Star Schema)**: Fact and dimension tables (`dim_*`, `fact_*`)[cite: 2]. All aggregations must occur in PostgreSQL/FastAPI SQL queries, **never** in application pandas/python code[cite: 2, 21].
- **Data Boundaries**: Streamlit (`dashboard/app.py`) must ONLY communicate with FastAPI (`api/`). Direct database connections from the dashboard are prohibited[cite: 2, 22].

## Code Conventions
- Python 3.12 syntax with strict type annotations.
- Use Pydantic v2 for attribute normalization and standard field casting[cite: 10, 19].
- API responses must use asyncpg parameterized queries (`$1`, `$2`) to avoid SQL injection[cite: 21].
