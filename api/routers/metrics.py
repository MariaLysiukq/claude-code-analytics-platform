"""Analytics/metrics endpoints for the dashboard.

All aggregation is done in SQL against the typed star schema (dim_employees,
dim_sessions, fact_api_requests, fact_tool_events, fact_api_errors) — the API
layer only shapes rows into response models.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, Query, Request

from api.schemas.metrics import (
    ActiveUsersByDay,
    CostByDay,
    CostByModel,
    CostByPractice,
    ErrorRatesResponse,
    ErrorTypeBreakdown,
    SessionStats,
    StatusCodeBreakdown,
    ToolReliability,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@dataclass
class DateRange:
    start: Optional[datetime]
    end: Optional[datetime]


def date_range(
    start_date: Optional[datetime] = Query(
        None, description="Inclusive lower bound (ISO 8601)."
    ),
    end_date: Optional[datetime] = Query(
        None, description="Exclusive upper bound (ISO 8601)."
    ),
) -> DateRange:
    return DateRange(start=start_date, end=end_date)


@router.get("/cost-by-model", response_model=list[CostByModel])
async def cost_by_model(
    request: Request, range: DateRange = Depends(date_range)
) -> list[CostByModel]:
    """Token usage and spend, grouped by model."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        SELECT
            model,
            COUNT(*) AS request_count,
            COALESCE(SUM(input_tokens), 0)::bigint AS total_input_tokens,
            COALESCE(SUM(output_tokens), 0)::bigint AS total_output_tokens,
            COALESCE(SUM(cache_read_tokens), 0)::bigint AS total_cache_read_tokens,
            COALESCE(SUM(cache_creation_tokens), 0)::bigint AS total_cache_creation_tokens,
            COALESCE(SUM(cost_usd), 0)::float8 AS total_cost_usd,
            COALESCE(AVG(cost_usd), 0)::float8 AS avg_cost_usd,
            COALESCE(AVG(duration_ms), 0)::float8 AS avg_duration_ms
        FROM fact_api_requests
        WHERE model IS NOT NULL
          AND ($1::timestamptz IS NULL OR event_timestamp >= $1)
          AND ($2::timestamptz IS NULL OR event_timestamp < $2)
        GROUP BY model
        ORDER BY total_cost_usd DESC
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, range.start, range.end)
    return [CostByModel(**row) for row in rows]


@router.get("/cost-by-practice", response_model=list[CostByPractice])
async def cost_by_practice(
    request: Request, range: DateRange = Depends(date_range)
) -> list[CostByPractice]:
    """Token usage and spend, grouped by employee practice."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        SELECT
            COALESCE(e.practice, 'Unknown') AS practice,
            COUNT(DISTINCT r.session_id) AS session_count,
            COUNT(*) AS request_count,
            COALESCE(
                SUM(COALESCE(r.input_tokens, 0) + COALESCE(r.output_tokens, 0)), 0
            )::bigint AS total_tokens,
            COALESCE(SUM(r.cost_usd), 0)::float8 AS total_cost_usd,
            COALESCE(AVG(r.cost_usd), 0)::float8 AS avg_cost_per_request
        FROM fact_api_requests r
        LEFT JOIN dim_employees e ON e.email = r.user_email
        WHERE ($1::timestamptz IS NULL OR r.event_timestamp >= $1)
          AND ($2::timestamptz IS NULL OR r.event_timestamp < $2)
        GROUP BY e.practice
        ORDER BY total_cost_usd DESC
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, range.start, range.end)
    return [CostByPractice(**row) for row in rows]


@router.get("/cost-by-day", response_model=list[CostByDay])
async def cost_by_day(
    request: Request, range: DateRange = Depends(date_range)
) -> list[CostByDay]:
    """Daily spend and token usage, for a historical cost trend line."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        SELECT
            date_trunc('day', event_timestamp)::date AS activity_date,
            COUNT(*) AS request_count,
            COALESCE(
                SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0
            )::bigint AS total_tokens,
            COALESCE(SUM(cost_usd), 0)::float8 AS total_cost_usd
        FROM fact_api_requests
        WHERE event_timestamp IS NOT NULL
          AND ($1::timestamptz IS NULL OR event_timestamp >= $1)
          AND ($2::timestamptz IS NULL OR event_timestamp < $2)
        GROUP BY 1
        ORDER BY 1
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, range.start, range.end)
    return [CostByDay(**row) for row in rows]


@router.get("/tool-reliability", response_model=list[ToolReliability])
async def tool_reliability(
    request: Request, range: DateRange = Depends(date_range)
) -> list[ToolReliability]:
    """Acceptance and success rates per tool, for gauging agent tool efficiency."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        SELECT
            tool_name,
            COUNT(*) AS total_calls,
            COUNT(*) FILTER (WHERE decision = 'accept') AS accepted_count,
            COUNT(*) FILTER (WHERE decision = 'reject') AS rejected_count,
            COUNT(*) FILTER (WHERE success IS TRUE) AS success_count,
            COUNT(*) FILTER (WHERE success IS FALSE) AS failure_count,
            (COUNT(*) FILTER (WHERE decision = 'accept'))::float8
                / NULLIF(COUNT(*) FILTER (WHERE decision IS NOT NULL), 0) AS acceptance_rate,
            (COUNT(*) FILTER (WHERE success IS TRUE))::float8
                / NULLIF(COUNT(*) FILTER (WHERE success IS NOT NULL), 0) AS success_rate,
            COALESCE(AVG(duration_ms), 0)::float8 AS avg_duration_ms
        FROM fact_tool_events
        WHERE ($1::timestamptz IS NULL OR COALESCE(decision_timestamp, result_timestamp) >= $1)
          AND ($2::timestamptz IS NULL OR COALESCE(decision_timestamp, result_timestamp) < $2)
        GROUP BY tool_name
        ORDER BY total_calls DESC
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, range.start, range.end)
    return [ToolReliability(**row) for row in rows]


@router.get("/active-users", response_model=list[ActiveUsersByDay])
async def active_users(
    request: Request, range: DateRange = Depends(date_range)
) -> list[ActiveUsersByDay]:
    """Daily active users and session counts, for a usage-over-time trend line."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        SELECT
            date_trunc('day', started_at)::date AS activity_date,
            COUNT(DISTINCT user_email) AS active_users,
            COUNT(*) AS session_count
        FROM dim_sessions
        WHERE started_at IS NOT NULL
          AND ($1::timestamptz IS NULL OR started_at >= $1)
          AND ($2::timestamptz IS NULL OR started_at < $2)
        GROUP BY 1
        ORDER BY 1
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, range.start, range.end)
    return [ActiveUsersByDay(**row) for row in rows]


@router.get("/error-rates", response_model=ErrorRatesResponse)
async def error_rates(
    request: Request, range: DateRange = Depends(date_range)
) -> ErrorRatesResponse:
    """API error breakdown by error type, plus an overall error rate."""
    pool: asyncpg.Pool = request.app.state.pool
    breakdown_query = """
        SELECT
            COALESCE(error, 'unknown') AS error_type,
            COUNT(*) AS error_count,
            COUNT(DISTINCT session_id) AS affected_sessions,
            COALESCE(AVG(duration_ms), 0)::float8 AS avg_duration_ms
        FROM fact_api_errors
        WHERE ($1::timestamptz IS NULL OR event_timestamp >= $1)
          AND ($2::timestamptz IS NULL OR event_timestamp < $2)
        GROUP BY error
        ORDER BY error_count DESC
    """
    totals_query = """
        SELECT
            (SELECT COUNT(*) FROM fact_api_requests
              WHERE ($1::timestamptz IS NULL OR event_timestamp >= $1)
                AND ($2::timestamptz IS NULL OR event_timestamp < $2)) AS total_requests,
            (SELECT COUNT(*) FROM fact_api_errors
              WHERE ($1::timestamptz IS NULL OR event_timestamp >= $1)
                AND ($2::timestamptz IS NULL OR event_timestamp < $2)) AS total_errors
    """
    async with pool.acquire() as connection:
        breakdown_rows = await connection.fetch(breakdown_query, range.start, range.end)
        totals_row = await connection.fetchrow(totals_query, range.start, range.end)

    total_requests = totals_row["total_requests"]
    total_errors = totals_row["total_errors"]
    total_attempts = total_requests + total_errors
    error_rate = total_errors / total_attempts if total_attempts else 0.0

    return ErrorRatesResponse(
        total_requests=total_requests,
        total_errors=total_errors,
        error_rate=error_rate,
        by_type=[ErrorTypeBreakdown(**row) for row in breakdown_rows],
    )


@router.get("/status-codes", response_model=list[StatusCodeBreakdown])
async def status_codes(
    request: Request, range: DateRange = Depends(date_range)
) -> list[StatusCodeBreakdown]:
    """HTTP status code distribution across API errors."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        SELECT
            status_code,
            COUNT(*) AS error_count
        FROM fact_api_errors
        WHERE ($1::timestamptz IS NULL OR event_timestamp >= $1)
          AND ($2::timestamptz IS NULL OR event_timestamp < $2)
        GROUP BY status_code
        ORDER BY error_count DESC
    """
    async with pool.acquire() as connection:
        rows = await connection.fetch(query, range.start, range.end)
    return [StatusCodeBreakdown(**row) for row in rows]


@router.get("/session-stats", response_model=SessionStats)
async def session_stats(
    request: Request, range: DateRange = Depends(date_range)
) -> SessionStats:
    """Fleet-wide session shape: duration, event/prompt counts, cost and tokens."""
    pool: asyncpg.Pool = request.app.state.pool
    query = """
        WITH session_costs AS (
            SELECT
                session_id,
                COALESCE(SUM(cost_usd), 0) AS session_cost,
                COALESCE(SUM(COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0)), 0)
                    AS session_tokens
            FROM fact_api_requests
            GROUP BY session_id
        )
        SELECT
            COUNT(*) AS total_sessions,
            COALESCE(
                AVG(EXTRACT(EPOCH FROM (s.ended_at - s.started_at))), 0
            )::float8 AS avg_duration_seconds,
            COALESCE(
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (s.ended_at - s.started_at))
                ), 0
            )::float8 AS median_duration_seconds,
            COALESCE(AVG(s.event_count), 0)::float8 AS avg_event_count,
            COALESCE(AVG(s.prompt_count), 0)::float8 AS avg_prompt_count,
            COALESCE(AVG(sc.session_cost), 0)::float8 AS avg_cost_usd,
            COALESCE(AVG(sc.session_tokens), 0)::float8 AS avg_tokens
        FROM dim_sessions s
        LEFT JOIN session_costs sc ON sc.session_id = s.session_id
        WHERE ($1::timestamptz IS NULL OR s.started_at >= $1)
          AND ($2::timestamptz IS NULL OR s.started_at < $2)
    """
    async with pool.acquire() as connection:
        row = await connection.fetchrow(query, range.start, range.end)
    return SessionStats(**row)
