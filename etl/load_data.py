#!/usr/bin/env python3
"""ETL entrypoint: load data/employees.csv and data/telemetry_logs.jsonl into
Postgres per the two-layer model described in PROJECT_PLAN.md section 4.1.

Usage:
    python -m etl.load_data [--truncate] [--batch-size N]

Idempotent by default: every insert uses ON CONFLICT so re-running the
script against already-loaded data does not create duplicates or error out.
Pass --truncate for a clean full reload instead.

Processing is two passes over the telemetry file:
  1. build dim_sessions (session_id is a FK target for every fact table, so
     sessions must exist before fact rows referencing them are inserted)
  2. stream raw_events + fact_user_prompts + fact_api_requests +
     fact_tool_events + fact_api_errors
Both passes stream the file line-by-line -- the 57MB source is never fully
loaded into memory.
"""
import argparse
import csv
import logging
import sys
import time
from datetime import datetime, timezone

from pydantic import ValidationError

from . import config, db
from .models import (
    ApiErrorAttributes,
    ApiRequestAttributes,
    EmployeeRecord,
    ToolDecisionAttributes,
    ToolResultAttributes,
    UserPromptAttributes,
)
from .parsing import iter_parsed_events
from .tool_reconciler import ToolEventReconciler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("etl.load_data")

from psycopg2.extras import Json

# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

UPSERT_EMPLOYEES_SQL = """
INSERT INTO dim_employees (email, full_name, practice, level, location)
VALUES %s
ON CONFLICT (email) DO UPDATE SET
    full_name = EXCLUDED.full_name,
    practice  = EXCLUDED.practice,
    level     = EXCLUDED.level,
    location  = EXCLUDED.location
"""

UPSERT_SESSIONS_SQL = """
INSERT INTO dim_sessions (
    session_id, user_email, organization_id, terminal_type, os_type,
    os_version, host_name, host_arch, started_at, ended_at, event_count,
    prompt_count
) VALUES %s
ON CONFLICT (session_id) DO UPDATE SET
    user_email      = EXCLUDED.user_email,
    organization_id = EXCLUDED.organization_id,
    terminal_type   = EXCLUDED.terminal_type,
    os_type         = EXCLUDED.os_type,
    os_version      = EXCLUDED.os_version,
    host_name       = EXCLUDED.host_name,
    host_arch       = EXCLUDED.host_arch,
    started_at      = EXCLUDED.started_at,
    ended_at        = EXCLUDED.ended_at,
    event_count     = EXCLUDED.event_count,
    prompt_count    = EXCLUDED.prompt_count
"""

INSERT_RAW_EVENTS_SQL = """
INSERT INTO raw_events (id, body, session_id, user_email, event_timestamp, payload)
VALUES %s
ON CONFLICT (id) DO NOTHING
"""

INSERT_USER_PROMPTS_SQL = """
INSERT INTO fact_user_prompts (id, session_id, user_email, event_timestamp, prompt_length)
VALUES %s
ON CONFLICT (id) DO NOTHING
"""

INSERT_API_REQUESTS_SQL = """
INSERT INTO fact_api_requests (
    id, session_id, user_email, event_timestamp, model, input_tokens,
    output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd,
    duration_ms
) VALUES %s
ON CONFLICT (id) DO NOTHING
"""

INSERT_API_ERRORS_SQL = """
INSERT INTO fact_api_errors (
    id, session_id, user_email, event_timestamp, model, error, status_code,
    attempt, duration_ms
) VALUES %s
ON CONFLICT (id) DO NOTHING
"""

UPSERT_TOOL_EVENTS_SQL = """
INSERT INTO fact_tool_events (
    id, session_id, user_email, tool_name, decision_event_id, decision,
    decision_source, decision_timestamp, result_event_id, success,
    decision_type, tool_result_size_bytes, duration_ms, result_timestamp
) VALUES %s
ON CONFLICT (id) DO UPDATE SET
    session_id              = EXCLUDED.session_id,
    user_email              = EXCLUDED.user_email,
    tool_name                = EXCLUDED.tool_name,
    decision_event_id        = EXCLUDED.decision_event_id,
    decision                 = EXCLUDED.decision,
    decision_source           = EXCLUDED.decision_source,
    decision_timestamp        = EXCLUDED.decision_timestamp,
    result_event_id           = EXCLUDED.result_event_id,
    success                   = EXCLUDED.success,
    decision_type             = EXCLUDED.decision_type,
    tool_result_size_bytes    = EXCLUDED.tool_result_size_bytes,
    duration_ms               = EXCLUDED.duration_ms,
    result_timestamp          = EXCLUDED.result_timestamp
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class Counters:
    """Tracks rows sent per table plus rows skipped for validation failures."""

    def __init__(self):
        self.sent = {}
        self.skipped = {}

    def add_sent(self, table: str, n: int) -> None:
        self.sent[table] = self.sent.get(table, 0) + n

    def add_skipped(self, table: str, n: int = 1) -> None:
        self.skipped[table] = self.skipped.get(table, 0) + n

    def report(self) -> None:
        logger.info("=" * 60)
        logger.info("Load summary")
        for table in sorted(set(self.sent) | set(self.skipped)):
            logger.info(
                "  %-22s sent=%-8d skipped=%d",
                table,
                self.sent.get(table, 0),
                self.skipped.get(table, 0),
            )
        logger.info("=" * 60)


def parse_event_timestamp(attributes: dict, log_timestamp_ms):
    raw = attributes.get("event_timestamp")
    if raw:
        try:
            return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            pass
    if log_timestamp_ms:
        try:
            return datetime.fromtimestamp(int(log_timestamp_ms) / 1000, tz=timezone.utc)
        except (ValueError, OSError, OverflowError, TypeError):
            pass
    return None


class Flusher:
    """Buffers rows per table and flushes in batches via execute_values."""

    def __init__(self, conn, batch_size: int, counters: Counters):
        self.conn = conn
        self.batch_size = batch_size
        self.counters = counters
        self._buffers = {}
        self._sql = {}

    def register(self, table: str, sql: str) -> None:
        self._buffers[table] = []
        self._sql[table] = sql

    def add(self, table: str, row: tuple) -> None:
        buf = self._buffers[table]
        buf.append(row)
        if len(buf) >= self.batch_size:
            self.flush(table)

    def flush(self, table: str) -> None:
        buf = self._buffers[table]
        if not buf:
            return
        n = db.execute_upsert(self.conn, self._sql[table], buf)
        self.counters.add_sent(table, n)
        logger.info("  -> %s: flushed %d rows (total sent so far: %d)", table, n, self.counters.sent[table])
        buf.clear()

    def flush_all(self) -> None:
        for table in self._buffers:
            self.flush(table)


# ---------------------------------------------------------------------------
# Load steps
# ---------------------------------------------------------------------------


def load_employees(conn, counters: Counters) -> set:
    """Load data/employees.csv into dim_employees. Returns the set of valid
    employee emails, used downstream to null out FK references to unknown
    users rather than fail an entire batch insert.
    """
    logger.info("Loading employees from %s", config.EMPLOYEES_CSV)
    rows = []
    known_emails = set()
    with open(config.EMPLOYEES_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for line_no, raw_row in enumerate(reader, start=2):
            try:
                rec = EmployeeRecord(**raw_row)
            except ValidationError as exc:
                logger.warning("employees.csv line %d: invalid row, skipping: %s", line_no, exc)
                counters.add_skipped("dim_employees")
                continue
            rows.append((rec.email, rec.full_name, rec.practice, rec.level, rec.location))
            known_emails.add(rec.email)

    n = db.execute_upsert(conn, UPSERT_EMPLOYEES_SQL, rows)
    counters.add_sent("dim_employees", n)
    conn.commit()
    logger.info("dim_employees: loaded %d rows", n)
    return known_emails


def build_sessions(conn, counters: Counters, known_emails: set, batch_size: int) -> None:
    """Pass 1: stream telemetry, aggregate per-session stats, upsert dim_sessions."""
    logger.info("Pass 1/2: deriving sessions from %s", config.TELEMETRY_JSONL)
    sessions: dict[str, dict] = {}
    unknown_emails_warned = set()
    n_events = 0

    for pe in iter_parsed_events(config.TELEMETRY_JSONL):
        n_events += 1
        session_id = pe.attributes.get("session_id")
        if not session_id:
            continue

        ts = parse_event_timestamp(pe.attributes, pe.log_timestamp_ms)
        email = pe.attributes.get("user_email")
        if email and email not in known_emails:
            if email not in unknown_emails_warned:
                logger.warning("session %s: user_email %r not found in dim_employees, will store as NULL", session_id, email)
                unknown_emails_warned.add(email)
            email = None

        entry = sessions.get(session_id)
        if entry is None:
            entry = {
                "session_id": session_id,
                "user_email": email,
                "organization_id": pe.attributes.get("organization_id"),
                "terminal_type": pe.attributes.get("terminal_type"),
                "os_type": pe.resource.get("os_type"),
                "os_version": pe.resource.get("os_version"),
                "host_name": pe.resource.get("host_name"),
                "host_arch": pe.resource.get("host_arch"),
                "started_at": ts,
                "ended_at": ts,
                "event_count": 0,
                "prompt_count": 0,
            }
            sessions[session_id] = entry
        else:
            if email and not entry["user_email"]:
                entry["user_email"] = email
            if ts:
                if entry["started_at"] is None or ts < entry["started_at"]:
                    entry["started_at"] = ts
                if entry["ended_at"] is None or ts > entry["ended_at"]:
                    entry["ended_at"] = ts

        entry["event_count"] += 1
        if pe.event_type == "user_prompt":
            entry["prompt_count"] += 1

        if n_events % config.LOG_EVERY_N_LINES == 0:
            logger.info("  ...scanned %d events, %d distinct sessions so far", n_events, len(sessions))

    logger.info("Pass 1/2 done: %d events scanned, %d distinct sessions found", n_events, len(sessions))

    rows = [
        (
            s["session_id"],
            s["user_email"],
            s["organization_id"],
            s["terminal_type"],
            s["os_type"],
            s["os_version"],
            s["host_name"],
            s["host_arch"],
            s["started_at"],
            s["ended_at"],
            s["event_count"],
            s["prompt_count"],
        )
        for s in sessions.values()
    ]
    total = 0
    for i in range(0, len(rows), batch_size):
        chunk = rows[i : i + batch_size]
        n = db.execute_upsert(conn, UPSERT_SESSIONS_SQL, chunk)
        total += n
        logger.info("  -> dim_sessions: flushed %d rows (total sent so far: %d)", n, total)
    counters.add_sent("dim_sessions", total)
    conn.commit()
    logger.info("dim_sessions: loaded %d rows", total)


def _decision_only_row(d: dict) -> tuple:
    """A tool_decision with no matching tool_result (e.g. a rejected call)."""
    return (
        d["id"],
        d["session_id"],
        d["user_email"],
        d["tool_name"],
        d["id"],
        d["decision"],
        d["source"],
        d["timestamp"],
        None,
        None,
        None,
        None,
        None,
        None,
    )


def _merged_tool_row(matched: dict, pe, attrs, session_id, email) -> tuple:
    """A tool_decision reconciled with its tool_result -- one row, PK'd on
    the decision's event id."""
    return (
        matched["id"],
        matched["session_id"] or session_id,
        matched["user_email"] or email,
        attrs.tool_name,
        matched["id"],
        matched["decision"],
        matched["source"],
        matched["timestamp"],
        pe.id,
        attrs.success,
        attrs.decision_type,
        attrs.tool_result_size_bytes,
        attrs.duration_ms,
        attrs.event_timestamp,
    )


def _result_only_row(pe, attrs, session_id, email) -> tuple:
    """A tool_result with no matching tool_decision (defensive fallback;
    not expected from the current data generator)."""
    return (
        pe.id,
        session_id,
        email,
        attrs.tool_name,
        None,
        attrs.decision_type,
        attrs.decision_source,
        None,
        pe.id,
        attrs.success,
        attrs.decision_type,
        attrs.tool_result_size_bytes,
        attrs.duration_ms,
        attrs.event_timestamp,
    )


def load_events(conn, counters: Counters, known_emails: set, batch_size: int) -> None:
    """Pass 2: stream telemetry again, populate raw_events + Layer 2 fact tables."""
    logger.info("Pass 2/2: loading events from %s", config.TELEMETRY_JSONL)

    flusher = Flusher(conn, batch_size, counters)
    flusher.register("raw_events", INSERT_RAW_EVENTS_SQL)
    flusher.register("fact_user_prompts", INSERT_USER_PROMPTS_SQL)
    flusher.register("fact_api_requests", INSERT_API_REQUESTS_SQL)
    flusher.register("fact_api_errors", INSERT_API_ERRORS_SQL)
    flusher.register("fact_tool_events", UPSERT_TOOL_EVENTS_SQL)

    reconciler = ToolEventReconciler()
    unknown_emails_warned = set()

    def resolve_email(email):
        if email and email not in known_emails:
            if email not in unknown_emails_warned:
                logger.warning("event references unknown user_email %r, will store as NULL", email)
                unknown_emails_warned.add(email)
            return None
        return email

    n_events = 0
    for pe in iter_parsed_events(config.TELEMETRY_JSONL):
        n_events += 1
        session_id = pe.attributes.get("session_id")
        raw_email = pe.attributes.get("user_email")
        email = resolve_email(raw_email)
        ts = parse_event_timestamp(pe.attributes, pe.log_timestamp_ms)

        # Layer 1: full-fidelity copy, independent of Layer-2 validation.
        flusher.add(
            "raw_events",
            (pe.id, pe.body, session_id, email, ts, Json(pe.payload)),
        )

        try:
            if pe.event_type == "user_prompt":
                attrs = UserPromptAttributes(**pe.attributes)
                flusher.add(
                    "fact_user_prompts",
                    (pe.id, session_id, email, attrs.event_timestamp, attrs.prompt_length),
                )

            elif pe.event_type == "api_request":
                attrs = ApiRequestAttributes(**pe.attributes)
                flusher.add(
                    "fact_api_requests",
                    (
                        pe.id,
                        session_id,
                        email,
                        attrs.event_timestamp,
                        attrs.model,
                        attrs.input_tokens,
                        attrs.output_tokens,
                        attrs.cache_read_tokens,
                        attrs.cache_creation_tokens,
                        attrs.cost_usd,
                        attrs.duration_ms,
                    ),
                )

            elif pe.event_type == "api_error":
                attrs = ApiErrorAttributes(**pe.attributes)
                flusher.add(
                    "fact_api_errors",
                    (
                        pe.id,
                        session_id,
                        email,
                        attrs.event_timestamp,
                        attrs.model,
                        attrs.error,
                        attrs.status_code,
                        attrs.attempt,
                        attrs.duration_ms,
                    ),
                )

            elif pe.event_type == "tool_decision":
                attrs = ToolDecisionAttributes(**pe.attributes)
                stale = reconciler.add_decision(
                    session_id,
                    {
                        "id": pe.id,
                        "session_id": session_id,
                        "user_email": email,
                        "tool_name": attrs.tool_name,
                        "decision": attrs.decision,
                        "source": attrs.source,
                        "timestamp": attrs.event_timestamp,
                    },
                )
                if stale:
                    flusher.add("fact_tool_events", _decision_only_row(stale))

            elif pe.event_type == "tool_result":
                attrs = ToolResultAttributes(**pe.attributes)
                matched, stale = reconciler.match_result(session_id, attrs.tool_name)
                if stale:
                    flusher.add("fact_tool_events", _decision_only_row(stale))
                if matched:
                    row = _merged_tool_row(matched, pe, attrs, session_id, email)
                else:
                    row = _result_only_row(pe, attrs, session_id, email)
                flusher.add("fact_tool_events", row)

        except ValidationError as exc:
            logger.warning("event %s (%s): validation failed, skipping typed row: %s", pe.id, pe.body, exc)
            counters.add_skipped(pe.body)

        if n_events % config.LOG_EVERY_N_LINES == 0:
            logger.info("  ...processed %d events", n_events)

    # Any decisions that never saw a matching result (e.g. rejected calls).
    for d in reconciler.drain_unmatched():
        flusher.add("fact_tool_events", _decision_only_row(d))

    flusher.flush_all()
    conn.commit()
    logger.info("Pass 2/2 done: %d events processed", n_events)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--truncate", action="store_true", help="Truncate all tables before loading (full reset instead of upsert).")
    parser.add_argument("--batch-size", type=int, default=config.BATCH_SIZE, help="Rows per batch insert.")
    args = parser.parse_args(argv)

    start = time.monotonic()
    logger.info("Connecting to %s", config.DATABASE_URL.split("@")[-1])
    conn = db.connect(config.DATABASE_URL)
    counters = Counters()

    try:
        if args.truncate:
            logger.info("--truncate given: wiping all tables before load")
            db.truncate_all(conn)
            conn.commit()

        known_emails = load_employees(conn, counters)
        build_sessions(conn, counters, known_emails, args.batch_size)
        load_events(conn, counters, known_emails, args.batch_size)
    except Exception:
        conn.rollback()
        logger.exception("Load failed, rolled back uncommitted work")
        return 1
    finally:
        conn.close()

    counters.report()
    logger.info("Done in %.1fs", time.monotonic() - start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
