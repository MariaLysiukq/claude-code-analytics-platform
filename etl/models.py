"""Pydantic models used to validate and cast telemetry fields.

The source data serializes almost every numeric field as a JSON string
(e.g. `"cost_usd": "0.093..."`), and a few fields use the literal string
"undefined" in place of a real null. These models centralize that casting
so a malformed/unexpected value fails validation cleanly and can be
logged + skipped by the caller instead of blowing up the whole load.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, field_validator


def _blank_to_none(value):
    if value is None:
        return None
    if isinstance(value, str) and value.strip().lower() in ("", "undefined", "null", "none"):
        return None
    return value


class EmployeeRecord(BaseModel):
    email: str
    full_name: str
    practice: str
    level: int
    location: str

    @field_validator("level", mode="before")
    @classmethod
    def parse_level(cls, v):
        if isinstance(v, str):
            v = v.strip().upper().lstrip("L")
        return int(v)


class CommonAttributes(BaseModel):
    """Fields present on every event's `attributes` block."""

    event_timestamp: datetime
    organization_id: Optional[str] = None
    session_id: Optional[str] = None
    terminal_type: Optional[str] = None
    user_email: Optional[str] = None
    user_id: Optional[str] = None


class UserPromptAttributes(CommonAttributes):
    prompt_length: Optional[int] = None

    _blank = field_validator("prompt_length", mode="before")(_blank_to_none)


class ApiRequestAttributes(CommonAttributes):
    model: Optional[str] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    duration_ms: Optional[int] = None

    _blank1 = field_validator(
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "cost_usd",
        "duration_ms",
        mode="before",
    )(_blank_to_none)


class ToolDecisionAttributes(CommonAttributes):
    tool_name: str
    decision: Optional[str] = None
    source: Optional[str] = None


class ToolResultAttributes(CommonAttributes):
    tool_name: str
    success: Optional[bool] = None
    duration_ms: Optional[int] = None
    decision_source: Optional[str] = None
    decision_type: Optional[str] = None
    tool_result_size_bytes: Optional[int] = None

    _blank = field_validator("duration_ms", "tool_result_size_bytes", mode="before")(
        _blank_to_none
    )

    @field_validator("success", mode="before")
    @classmethod
    def parse_success(cls, v):
        if isinstance(v, str):
            return v.strip().lower() == "true"
        return v


class ApiErrorAttributes(CommonAttributes):
    model: Optional[str] = None
    error: Optional[str] = None
    status_code: Optional[int] = None
    attempt: Optional[int] = None
    duration_ms: Optional[int] = None

    _blank = field_validator("status_code", "attempt", "duration_ms", mode="before")(
        _blank_to_none
    )
