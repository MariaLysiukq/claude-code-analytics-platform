"""Streamlit dashboard for the Claude Code Analytics platform.

Talks only to the FastAPI service (never Postgres directly), matching the
architecture in PROJECT_PLAN.md section 4.4. Two personas are exposed as
sidebar-selectable views: Executive/Finance (spend) and Developer/Engineering
(token usage, tool reliability, API errors).
"""
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

API_BASE_URL = os.environ.get("API_BASE_URL", "http://api:8000/api/v1").rstrip("/")
REQUEST_TIMEOUT_SECONDS = 8
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1.5
CACHE_TTL_SECONDS = 60

# Categorical palette (fixed order — see .claude dataviz skill / palette.md).
# Never cycle: a chart with more series than slots folds extras into "Other".
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
    "#e87ba4", "#008300", "#4a3aa7", "#e34948",
)
STATUS_GOOD, STATUS_WARNING, STATUS_SERIOUS, STATUS_CRITICAL = (
    "#0ca30c", "#fab219", "#ec835a", "#d03b3b",
)
MUTED_INK = "#898781"
FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"

CHART_LAYOUT = dict(
    template="plotly_white",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family=FONT_FAMILY, color="#52514e", size=13),
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
)

st.set_page_config(
    page_title="Claude Code Analytics",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# API access — resilient to the API still starting up or being unreachable.
# ---------------------------------------------------------------------------

def _request(endpoint: str, params: dict) -> object:
    """Fetch one endpoint with a short retry loop. Raises on final failure."""
    url = f"{API_BASE_URL}{endpoint}"
    last_error = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt < RETRY_ATTEMPTS - 1:
                time.sleep(RETRY_BACKOFF_SECONDS)
    raise RuntimeError(f"{endpoint} unreachable: {last_error}")


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _cached_request(endpoint: str, params_key: tuple) -> object:
    # Streamlit does not cache raised exceptions, so a failed call is retried
    # on the next rerun instead of freezing an error into the cache for the
    # full TTL window.
    return _request(endpoint, dict(params_key))


def fetch(endpoint: str, params: dict, label: str):
    """Cached GET with graceful degradation. Returns None on failure and
    surfaces a warning instead of crashing the page."""
    params_key = tuple(sorted((k, v) for k, v in params.items() if v is not None))
    try:
        return _cached_request(endpoint, params_key)
    except RuntimeError:
        st.warning(
            f"Couldn't load **{label}** — the API may still be starting up. "
            "Try the retry button in the sidebar."
        )
        return None


def check_api_health() -> bool:
    try:
        response = requests.get(f"{API_BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except requests.exceptions.RequestException:
        return False


def fmt_usd(value: float) -> str:
    return f"${value:,.2f}"


def fmt_int(value: float) -> str:
    return f"{value:,.0f}"


def fmt_pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def style_fig(fig):
    fig.update_layout(**CHART_LAYOUT)
    return fig


# ---------------------------------------------------------------------------
# Sidebar — connection status, persona switch, global date range filter.
# ---------------------------------------------------------------------------

st.sidebar.title("Claude Code Analytics")

api_healthy = check_api_health()
if api_healthy:
    st.sidebar.success("API connected")
else:
    st.sidebar.error("API unreachable")
    st.sidebar.caption(f"Trying: {API_BASE_URL}")

if st.sidebar.button("Retry / refresh data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.divider()

persona = st.sidebar.radio(
    "View",
    ["Executive / Finance", "Developer / Engineering"],
)

st.sidebar.divider()
st.sidebar.subheader("Date range filter")
start_date = st.sidebar.date_input("Start date", value=None)
end_date = st.sidebar.date_input("End date", value=None)

if start_date and end_date and start_date > end_date:
    st.sidebar.error("Start date must be before end date.")
    st.stop()

date_params = {}
if start_date:
    date_params["start_date"] = datetime.combine(start_date, datetime.min.time()).isoformat()
if end_date:
    # end_date is an exclusive upper bound server-side, so push it one day
    # forward to include the whole selected end day.
    exclusive_end = datetime.combine(end_date, datetime.min.time()) + timedelta(days=1)
    date_params["end_date"] = exclusive_end.isoformat()

st.sidebar.caption("Leave blank to include the full dataset history.")


# ---------------------------------------------------------------------------
# Executive / Finance view
# ---------------------------------------------------------------------------

def render_executive_view():
    st.title("Executive / Finance")
    st.caption("Spend overview across the fleet — cost trends, department and model breakdowns.")

    cost_by_day = fetch("/analytics/cost-by-day", date_params, "cost trend")
    cost_by_model = fetch("/analytics/cost-by-model", date_params, "cost by model")
    cost_by_practice = fetch("/analytics/cost-by-practice", date_params, "cost by practice")

    total_spend = sum(row["total_cost_usd"] for row in cost_by_model) if cost_by_model else 0.0
    total_requests = sum(row["request_count"] for row in cost_by_model) if cost_by_model else 0
    avg_cost = total_spend / total_requests if total_requests else 0.0

    col1, col2, col3 = st.columns(3)
    col1.metric("Total spend (USD)", fmt_usd(total_spend))
    col2.metric("Total API requests", fmt_int(total_requests))
    col3.metric("Avg cost / request", fmt_usd(avg_cost))

    st.subheader("Historical cost trend")
    if cost_by_day:
        df = pd.DataFrame(cost_by_day)
        df["activity_date"] = pd.to_datetime(df["activity_date"])
        fig = px.line(
            df, x="activity_date", y="total_cost_usd", markers=True,
            labels={"activity_date": "Date", "total_cost_usd": "Cost (USD)"},
        )
        fig.update_traces(line_color=BLUE, line_width=2, marker=dict(size=6, color=BLUE))
        fig.update_traces(hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>")
        st.plotly_chart(style_fig(fig), use_container_width=True)
        with st.expander("View data as table"):
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No cost trend data for the selected range.")

    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("Cost by department / practice")
        if cost_by_practice:
            df = pd.DataFrame(cost_by_practice).sort_values("total_cost_usd")
            fig = px.bar(
                df, x="total_cost_usd", y="practice", orientation="h",
                text=df["total_cost_usd"].map(fmt_usd),
                labels={"total_cost_usd": "Cost (USD)", "practice": ""},
            )
            fig.update_traces(marker_color=BLUE, textposition="outside")
            st.plotly_chart(style_fig(fig), use_container_width=True)
            with st.expander("View data as table"):
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No practice cost data for the selected range.")

    with col_right:
        st.subheader("Cost by AI model")
        if cost_by_model:
            df = pd.DataFrame(cost_by_model).sort_values("total_cost_usd")
            fig = px.bar(
                df, x="total_cost_usd", y="model", orientation="h",
                text=df["total_cost_usd"].map(fmt_usd),
                labels={"total_cost_usd": "Cost (USD)", "model": ""},
            )
            fig.update_traces(marker_color=ORANGE, textposition="outside")
            st.plotly_chart(style_fig(fig), use_container_width=True)
            with st.expander("View data as table"):
                st.dataframe(df, use_container_width=True, hide_index=True)
        else:
            st.info("No model cost data for the selected range.")


# ---------------------------------------------------------------------------
# Developer / Engineering view
# ---------------------------------------------------------------------------

def render_engineering_view():
    st.title("Developer / Engineering")
    st.caption("Token usage, tool reliability, and API error health.")

    cost_by_model = fetch("/analytics/cost-by-model", date_params, "token usage")
    tool_reliability = fetch("/analytics/tool-reliability", date_params, "tool reliability")
    error_rates = fetch("/analytics/error-rates", date_params, "error rates")
    status_codes = fetch("/analytics/status-codes", date_params, "status codes")

    st.subheader("Token consumption")
    if cost_by_model:
        df = pd.DataFrame(cost_by_model)
        total_input = df["total_input_tokens"].sum()
        total_output = df["total_output_tokens"].sum()
        total_cache_read = df["total_cache_read_tokens"].sum()
        total_cache_creation = df["total_cache_creation_tokens"].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Input tokens", fmt_int(total_input))
        c2.metric("Output tokens", fmt_int(total_output))
        c3.metric("Cache read tokens", fmt_int(total_cache_read))
        c4.metric("Cache creation tokens", fmt_int(total_cache_creation))

        token_cols = {
            "input_tokens": "Input",
            "output_tokens": "Output",
            "cache_read_tokens": "Cache read",
            "cache_creation_tokens": "Cache creation",
        }
        long_df = df.rename(columns={
            "total_input_tokens": "input_tokens",
            "total_output_tokens": "output_tokens",
            "total_cache_read_tokens": "cache_read_tokens",
            "total_cache_creation_tokens": "cache_creation_tokens",
        }).melt(
            id_vars=["model"], value_vars=list(token_cols.keys()),
            var_name="token_type", value_name="tokens",
        )
        long_df["token_type"] = long_df["token_type"].map(token_cols)
        fig = px.bar(
            long_df, x="model", y="tokens", color="token_type", barmode="group",
            color_discrete_map={
                "Input": BLUE, "Output": ORANGE,
                "Cache read": AQUA, "Cache creation": YELLOW,
            },
            labels={"model": "", "tokens": "Tokens", "token_type": ""},
        )
        st.plotly_chart(style_fig(fig), use_container_width=True)
        with st.expander("View data as table"):
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No token usage data for the selected range.")

    st.subheader("Tool execution success rates")
    if tool_reliability:
        df = pd.DataFrame(tool_reliability)
        df = df[df["success_rate"].notna()].sort_values("success_rate")
        fig = px.bar(
            df, x="success_rate", y="tool_name", orientation="h",
            text=df["success_rate"].map(fmt_pct),
            labels={"success_rate": "Success rate", "tool_name": ""},
        )
        fig.update_traces(marker_color=BLUE, textposition="outside")
        fig.update_xaxes(tickformat=".0%", range=[0, 1.08])
        st.plotly_chart(style_fig(fig), use_container_width=True)
        with st.expander("View data as table"):
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No tool reliability data for the selected range.")

    st.subheader("API errors")
    col_left, col_right = st.columns(2)

    with col_left:
        if error_rates:
            e1, e2, e3 = st.columns(3)
            e1.metric("Error rate", fmt_pct(error_rates["error_rate"]))
            e2.metric("Total requests", fmt_int(error_rates["total_requests"]))
            e3.metric("Total errors", fmt_int(error_rates["total_errors"]))

            if error_rates["by_type"]:
                df = pd.DataFrame(error_rates["by_type"]).sort_values("error_count")
                fig = px.bar(
                    df, x="error_count", y="error_type", orientation="h",
                    labels={"error_count": "Occurrences", "error_type": ""},
                )
                fig.update_traces(marker_color=BLUE)
                fig.update_yaxes(tickfont=dict(size=11))
                st.plotly_chart(style_fig(fig), use_container_width=True)
                with st.expander("View data as table"):
                    st.dataframe(df, use_container_width=True, hide_index=True)
            else:
                st.info("No errors recorded for the selected range.")
        else:
            st.info("No error rate data for the selected range.")

    with col_right:
        st.markdown("**HTTP status code distribution**")
        if status_codes:
            df = pd.DataFrame(status_codes)
            df["status_label"] = df["status_code"].apply(
                lambda code: str(int(code)) if pd.notna(code) else "Unknown"
            )

            def status_color(code):
                if pd.isna(code):
                    return MUTED_INK
                if 500 <= code < 600:
                    return STATUS_CRITICAL
                if 400 <= code < 500:
                    return STATUS_WARNING
                return STATUS_GOOD

            df["color"] = df["status_code"].apply(status_color)
            df = df.sort_values("error_count")
            fig = px.bar(
                df, x="error_count", y="status_label", orientation="h",
                labels={"error_count": "Occurrences", "status_label": "Status code"},
            )
            fig.update_traces(marker_color=df["color"])
            st.plotly_chart(style_fig(fig), use_container_width=True)
            st.caption("Color: green = 2xx/3xx, amber = 4xx, red = 5xx, gray = unknown.")
            with st.expander("View data as table"):
                st.dataframe(
                    df.drop(columns=["color"]), use_container_width=True, hide_index=True
                )
        else:
            st.info("No status code data for the selected range.")


# ---------------------------------------------------------------------------

if persona == "Executive / Finance":
    render_executive_view()
else:
    render_engineering_view()
