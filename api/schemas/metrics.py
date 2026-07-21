"""Pydantic response models for the analytics/metrics endpoints."""
from datetime import date
from typing import Optional

from pydantic import BaseModel


class CostByModel(BaseModel):
    model: str
    request_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_creation_tokens: int
    total_cost_usd: float
    avg_cost_usd: float
    avg_duration_ms: float


class CostByPractice(BaseModel):
    practice: str
    session_count: int
    request_count: int
    total_tokens: int
    total_cost_usd: float
    avg_cost_per_request: float


class ToolReliability(BaseModel):
    tool_name: str
    total_calls: int
    accepted_count: int
    rejected_count: int
    success_count: int
    failure_count: int
    acceptance_rate: Optional[float] = None
    success_rate: Optional[float] = None
    avg_duration_ms: float


class ActiveUsersByDay(BaseModel):
    activity_date: date
    active_users: int
    session_count: int


class ErrorTypeBreakdown(BaseModel):
    error_type: str
    error_count: int
    affected_sessions: int
    avg_duration_ms: float


class ErrorRatesResponse(BaseModel):
    total_requests: int
    total_errors: int
    error_rate: float
    by_type: list[ErrorTypeBreakdown]


class SessionStats(BaseModel):
    total_sessions: int
    avg_duration_seconds: float
    median_duration_seconds: float
    avg_event_count: float
    avg_prompt_count: float
    avg_cost_usd: float
    avg_tokens: float
