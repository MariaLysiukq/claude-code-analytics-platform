"""Matches claude_code.tool_decision events to their claude_code.tool_result
counterpart so both halves of one tool call land in a single fact_tool_events
row (see PROJECT_PLAN.md section 4.1 / open item in section 6).

Per the data generator (data/generate_fake_data.py): within one session, a
tool_decision is immediately followed by its tool_result *iff* the decision
was "accept" -- a "reject" decision never gets a result at all. Events are
globally sorted by timestamp with a stable sort, so a session's own events
stay in their original relative order in the final stream even though other
sessions' events interleave around them. That means at most one decision
per session is ever "open" (awaiting a result) at a time: a new decision
for a session implicitly means the previous one (if still open) was a
reject that will never be matched.

An earlier version of this matched FIFO per (session_id, tool_name), which
let a stale reject silently steal a later, unrelated accept+result pair for
the same tool name whenever that tool was called more than once in a
session. Tracking a single open decision per session avoids that.
"""


class ToolEventReconciler:
    def __init__(self):
        self._open: dict[str, dict] = {}  # session_id -> pending decision row

    def add_decision(self, session_id, decision_row: dict) -> dict | None:
        """Register a new decision as the session's open one. Returns the
        previous open decision for this session if it was never matched
        (the caller should flush it as a decision-only row), else None.
        """
        stale = self._open.get(session_id)
        self._open[session_id] = decision_row
        return stale

    def match_result(self, session_id, tool_name):
        """Returns (matched, stale):
        - matched: the open decision to merge with this result, or None.
        - stale: a same-session open decision for a *different* tool_name
          that must be flushed decision-only, since this result can't be
          its pair (defensive -- shouldn't occur with well-formed input).
        """
        pending = self._open.get(session_id)
        if pending is None:
            return None, None
        del self._open[session_id]
        if pending["tool_name"] == tool_name:
            return pending, None
        return None, pending

    def drain_unmatched(self):
        """Yield remaining open decisions that never received a result."""
        yield from self._open.values()
        self._open.clear()
