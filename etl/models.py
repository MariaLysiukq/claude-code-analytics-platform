"""Pydantic models used to validate and cast telemetry fields.

The source data serializes almost every numeric field as a JSON string
(e.g. `"cost_usd": "0.093..."`), and a few fields use the literal string
"undefined" in place of a real null. These models centralize that casting
so a malformed/unexpected value fails validation cleanly and can be
logged + skipped by the caller instead of blowing up the whole load.
"""

from datetime import datetime

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
    organization_id: str | None = None
    session_id: str | None = None
    terminal_type: str | None = None
    user_email: str | None = None
    user_id: str | None = None


class UserPromptAttributes(CommonAttributes):
    prompt_length: int | None = None

    _blank = field_validator("prompt_length", mode="before")(_blank_to_none)


class ApiRequestAttributes(CommonAttributes):
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_tokens: int | None = None
    cache_creation_tokens: int | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None

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
    decision: str | None = None
    source: str | None = None


class ToolResultAttributes(CommonAttributes):
    tool_name: str
    success: bool | None = None
    duration_ms: int | None = None
    decision_source: str | None = None
    decision_type: str | None = None
    tool_result_size_bytes: int | None = None

    _blank = field_validator("duration_ms", "tool_result_size_bytes", mode="before")(_blank_to_none)

    @field_validator("success", mode="before")
    @classmethod
    def parse_success(cls, v):
        if isinstance(v, str):
            return v.strip().lower() == "true"
        return v


class ApiErrorAttributes(CommonAttributes):
    model: str | None = None
    error: str | None = None
    status_code: int | None = None
    attempt: int | None = None
    duration_ms: int | None = None

    _blank = field_validator("status_code", "attempt", "duration_ms", mode="before")(_blank_to_none)
