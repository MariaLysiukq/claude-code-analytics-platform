-- Claude Code Usage Analytics Platform — database schema
-- Two-layer model: raw_events (append-only JSONB landing zone) + typed star
-- schema (dim_employees, dim_sessions, fact_*) for fast analytical queries.
-- See PROJECT_PLAN.md section 4.1 for rationale.

-- =========================================================================
-- Layer 1: raw landing zone
-- =========================================================================

CREATE TABLE raw_events (
    id                  TEXT PRIMARY KEY,          -- logEvents[].id
    body                TEXT NOT NULL,              -- claude_code.* event type
    session_id          TEXT,
    user_email          TEXT,
    event_timestamp     TIMESTAMPTZ,
    payload             JSONB NOT NULL,             -- full parsed message: body/attributes/scope/resource
    ingested_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_raw_events_body ON raw_events (body);
CREATE INDEX idx_raw_events_session_id ON raw_events (session_id);
CREATE INDEX idx_raw_events_user_email ON raw_events (user_email);
CREATE INDEX idx_raw_events_event_timestamp ON raw_events (event_timestamp);
CREATE INDEX idx_raw_events_payload_gin ON raw_events USING GIN (payload);

-- =========================================================================
-- Layer 2: typed star schema
-- =========================================================================

CREATE TABLE dim_employees (
    email               TEXT PRIMARY KEY,
    full_name           TEXT NOT NULL,
    practice            TEXT NOT NULL,
    level               SMALLINT NOT NULL,
    location            TEXT NOT NULL
);

CREATE TABLE dim_sessions (
    session_id          TEXT PRIMARY KEY,
    user_email          TEXT REFERENCES dim_employees (email),
    organization_id     TEXT,
    terminal_type       TEXT,
    os_type             TEXT,
    os_version          TEXT,
    host_name           TEXT,
    host_arch           TEXT,
    started_at          TIMESTAMPTZ,
    ended_at            TIMESTAMPTZ,
    event_count         INTEGER NOT NULL DEFAULT 0,
    prompt_count         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_dim_sessions_user_email ON dim_sessions (user_email);
CREATE INDEX idx_dim_sessions_started_at ON dim_sessions (started_at);

CREATE TABLE fact_user_prompts (
    id                  TEXT PRIMARY KEY,          -- source raw_events.id
    session_id          TEXT REFERENCES dim_sessions (session_id),
    user_email          TEXT REFERENCES dim_employees (email),
    event_timestamp     TIMESTAMPTZ NOT NULL,
    prompt_length       INTEGER
);

CREATE INDEX idx_fact_user_prompts_session_id ON fact_user_prompts (session_id);
CREATE INDEX idx_fact_user_prompts_user_email ON fact_user_prompts (user_email);
CREATE INDEX idx_fact_user_prompts_event_timestamp ON fact_user_prompts (event_timestamp);

CREATE TABLE fact_api_requests (
    id                  TEXT PRIMARY KEY,          -- source raw_events.id
    session_id          TEXT REFERENCES dim_sessions (session_id),
    user_email          TEXT REFERENCES dim_employees (email),
    event_timestamp     TIMESTAMPTZ NOT NULL,
    model               TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cache_read_tokens   INTEGER,
    cache_creation_tokens INTEGER,
    cost_usd            NUMERIC(12, 6),
    duration_ms         INTEGER
);

CREATE INDEX idx_fact_api_requests_session_id ON fact_api_requests (session_id);
CREATE INDEX idx_fact_api_requests_user_email ON fact_api_requests (user_email);
CREATE INDEX idx_fact_api_requests_event_timestamp ON fact_api_requests (event_timestamp);
CREATE INDEX idx_fact_api_requests_model ON fact_api_requests (model);

-- tool_decision and tool_result events reconciled into one row per tool call
-- where possible (matched by session_id + tool_name + time adjacency).
CREATE TABLE fact_tool_events (
    id                  TEXT PRIMARY KEY,          -- decision event id, falling back to result event id
    session_id          TEXT REFERENCES dim_sessions (session_id),
    user_email          TEXT REFERENCES dim_employees (email),
    tool_name           TEXT NOT NULL,
    decision_event_id   TEXT,
    decision            TEXT,                      -- accept / reject
    decision_source     TEXT,
    decision_timestamp  TIMESTAMPTZ,
    result_event_id     TEXT,
    success             BOOLEAN,
    decision_type       TEXT,
    tool_result_size_bytes INTEGER,
    duration_ms         INTEGER,
    result_timestamp    TIMESTAMPTZ
);

CREATE INDEX idx_fact_tool_events_session_id ON fact_tool_events (session_id);
CREATE INDEX idx_fact_tool_events_user_email ON fact_tool_events (user_email);
CREATE INDEX idx_fact_tool_events_tool_name ON fact_tool_events (tool_name);
CREATE INDEX idx_fact_tool_events_decision_timestamp ON fact_tool_events (decision_timestamp);

CREATE TABLE fact_api_errors (
    id                  TEXT PRIMARY KEY,          -- source raw_events.id
    session_id          TEXT REFERENCES dim_sessions (session_id),
    user_email          TEXT REFERENCES dim_employees (email),
    event_timestamp     TIMESTAMPTZ NOT NULL,
    model               TEXT,
    error                TEXT,
    status_code         INTEGER,
    attempt             INTEGER,
    duration_ms         INTEGER
);

CREATE INDEX idx_fact_api_errors_session_id ON fact_api_errors (session_id);
CREATE INDEX idx_fact_api_errors_user_email ON fact_api_errors (user_email);
CREATE INDEX idx_fact_api_errors_event_timestamp ON fact_api_errors (event_timestamp);
