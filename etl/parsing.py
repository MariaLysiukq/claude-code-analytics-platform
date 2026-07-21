"""Streaming parser for the CloudWatch-style telemetry_logs.jsonl file.

Each source line is a log batch containing `logEvents[]`. Each logEvent's
`message` field is itself a JSON-encoded string that must be parsed a
second time to get at `body` / `attributes` / `scope` / `resource`.
Malformed lines/events are logged and skipped rather than raising, so one
bad record doesn't abort the whole load.
"""
import json
import logging
from typing import Iterator, NamedTuple, Optional

logger = logging.getLogger(__name__)

# Source JSON uses dotted keys (e.g. "event.timestamp"); normalize to
# snake_case so they line up with Python identifiers / pydantic fields.
ATTR_KEY_MAP = {
    "event.timestamp": "event_timestamp",
    "organization.id": "organization_id",
    "session.id": "session_id",
    "terminal.type": "terminal_type",
    "user.account_uuid": "account_uuid",
    "user.email": "user_email",
    "user.id": "user_id",
}

RESOURCE_KEY_MAP = {
    "host.arch": "host_arch",
    "host.name": "host_name",
    "os.type": "os_type",
    "os.version": "os_version",
    "service.name": "service_name",
    "service.version": "service_version",
    "user.practice": "user_practice",
    "user.profile": "user_profile",
    "user.serial": "user_serial",
}


class ParsedEvent(NamedTuple):
    id: str
    body: str  # e.g. "claude_code.user_prompt"
    event_type: str  # e.g. "user_prompt"
    attributes: dict  # snake_case-normalized attributes
    resource: dict  # snake_case-normalized resource
    payload: dict  # full original parsed message (for raw_events JSONB)
    log_timestamp_ms: Optional[int]


def _normalize(d: dict, key_map: dict) -> dict:
    out = dict(d)
    for src, dst in key_map.items():
        if src in out:
            out[dst] = out.pop(src)
    return out


def iter_parsed_events(path) -> Iterator[ParsedEvent]:
    """Stream-parse `path`, yielding one ParsedEvent per logEvents[] entry."""
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                batch = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("line %d: failed to parse batch JSON: %s", line_no, exc)
                continue

            for log_event in batch.get("logEvents", []):
                event_id = log_event.get("id")
                raw_message = log_event.get("message")
                if not event_id or not raw_message:
                    logger.warning(
                        "line %d: logEvent missing id/message, skipping", line_no
                    )
                    continue
                try:
                    message = json.loads(raw_message)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "line %d: event %s failed to parse message JSON: %s",
                        line_no,
                        event_id,
                        exc,
                    )
                    continue

                body = message.get("body")
                if not body:
                    logger.warning(
                        "line %d: event %s missing body, skipping", line_no, event_id
                    )
                    continue

                attributes = _normalize(message.get("attributes", {}) or {}, ATTR_KEY_MAP)
                resource = _normalize(message.get("resource", {}) or {}, RESOURCE_KEY_MAP)

                yield ParsedEvent(
                    id=event_id,
                    body=body,
                    event_type=body.split(".", 1)[-1],
                    attributes=attributes,
                    resource=resource,
                    payload=message,
                    log_timestamp_ms=log_event.get("timestamp"),
                )
