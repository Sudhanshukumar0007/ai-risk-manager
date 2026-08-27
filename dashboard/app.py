"""AI Risk Manager — Streamlit Dashboard (Day 9, Part 1).

Panels
------
1. Live Audit Feed        — most-recent N scored orders, auto-refreshing.
2. Risk Distribution      — gauge / histogram of risk score spread and tier mix.
3. SHAP Importance Cards  — top-3 feature attributions for each visible order.
4. System Health Sidebar  — DB row-count KPIs, LLM status breakdown.

Caching strategy
----------------
All DB queries are wrapped with st.cache_data(ttl=CACHE_TTL_SECS) so the
dashboard does not hammer Postgres on every Streamlit re-run.  The TTL is
intentionally short (10 s default, tunable via DASHBOARD_CACHE_TTL env var)
so the feed feels live while protecting the database under load.

Connection
----------
The dashboard reads the DATABASE_URL_SYNC env var (psycopg2 / synchronous
Postgres URL) or DATABASE_URL and strips the async driver prefix.  It uses
plain psycopg2 through SQLAlchemy (create_engine) so it works both inside
and outside Docker.

Run locally (inside Docker):
    docker compose exec api streamlit run dashboard/app.py --server.port 8501

Run on host (needs .env or DATABASE_URL_SYNC exported):
    streamlit run dashboard/app.py
"""

import json
import logging
import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import create_engine, text

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
CACHE_TTL_SECS: int = int(os.getenv("DASHBOARD_CACHE_TTL", "10"))
DEFAULT_FEED_LIMIT: int = 50
PAGE_TITLE = "AI Risk Manager — Live Dashboard"

# Tier colours
TIER_COLOURS = {
    "ALLOW_COD": "#22c55e",       # green-500
    "NUDGE_PREPAY": "#f59e0b",    # amber-500
    "SOFT_GATE_COD": "#ef4444",   # red-500
    "unknown": "#6b7280",         # gray-500
}

# ── Database connection ───────────────────────────────────────────────────────

def _resolve_db_url() -> str:
    """Return a synchronous psycopg2-compatible DATABASE_URL."""
    # Prefer the explicit sync URL
    url = os.getenv("DATABASE_URL_SYNC", "")
    if not url:
        url = os.getenv("DATABASE_URL", "")
    if not url:
        url = "postgresql://risk_user:risk_pass@localhost:5432/risk_db"

    # Strip async driver prefixes that psycopg2 doesn't understand
    for prefix in ("postgresql+asyncpg://", "postgresql+aiopg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
    return url


@st.cache_resource
def get_engine():
    """Cached SQLAlchemy engine — created once per Streamlit session."""
    db_url = _resolve_db_url()
    return create_engine(db_url, pool_pre_ping=True, pool_size=2, max_overflow=3)


# ── Cached data loaders ───────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_SECS, show_spinner=False)
def load_audit_feed(limit: int = DEFAULT_FEED_LIMIT) -> pd.DataFrame:
    """Load the most-recent *limit* rows from audit_log."""
    sql = text("""
        SELECT
            al.event_id,
            al.order_id,
            al.score,
            al.tier,
            al.action,
            al.shap_values_json,
            al.created_at,
            le.explanation_text,
            le.status AS explanation_status
        FROM audit_log al
        LEFT JOIN llm_explanations le ON le.event_id = al.event_id
        ORDER BY al.created_at DESC
        LIMIT :limit
    """)
    try:
        with get_engine().connect() as conn:
            df = pd.read_sql(sql, conn, params={"limit": limit})
        return df
    except Exception as exc:
        logger.error("load_audit_feed failed: %s", exc)
        return pd.DataFrame()


@st.cache_data(ttl=CACHE_TTL_SECS, show_spinner=False)
def load_summary_stats() -> dict:
    """Aggregate KPIs for the header cards."""
    sql = text("""
        SELECT
            COUNT(*)                                           AS total_scored,
            COUNT(*) FILTER (WHERE tier = 'ALLOW_COD')        AS allow_cod,
            COUNT(*) FILTER (WHERE tier = 'NUDGE_PREPAY')     AS nudge_prepay,
            COUNT(*) FILTER (WHERE tier = 'SOFT_GATE_COD')    AS soft_gate_cod,
            AVG(score)                                         AS avg_score,
            MIN(score)                                         AS min_score,
            MAX(score)                                         AS max_score,
            COUNT(*) FILTER (WHERE score IS NOT NULL AND score >= 0.5) AS high_risk_count
        FROM audit_log
    """)
    try:
        with get_engine().connect() as conn:
            row = conn.execute(sql).mappings().first()
        return dict(row) if row else {}
    except Exception as exc:
        logger.error("load_summary_stats failed: %s", exc)
        return {}


@st.cache_data(ttl=CACHE_TTL_SECS, show_spinner=False)
def load_llm_breakdown() -> dict:
    """LLM explanation status breakdown."""
    sql = text("""
        SELECT status, COUNT(*) AS cnt
        FROM llm_explanations
        GROUP BY status
    """)
    try:
        with get_engine().connect() as conn:
            rows = conn.execute(sql).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception as exc:
        logger.error("load_llm_breakdown failed: %s", exc)
        return {}


@st.cache_data(ttl=CACHE_TTL_SECS, show_spinner=False)
def load_score_timeseries(hours: int = 24) -> pd.DataFrame:
    """Score time-series for sparkline (last *hours* hours, bucketed by minute)."""
    sql = text("""
        SELECT
            DATE_TRUNC('minute', created_at) AS bucket,
            AVG(score) AS avg_score,
            COUNT(*) AS order_count
        FROM audit_log
        WHERE created_at >= NOW() - (:hours * INTERVAL '1 hour')
        GROUP BY 1
        ORDER BY 1
    """)
    try:
        with get_engine().connect() as conn:
            df = pd.read_sql(sql, conn, params={"hours": hours})
        return df
    except Exception as exc:
        logger.error("load_score_timeseries failed: %s", exc)
        return pd.DataFrame()


# ── UI helpers ────────────────────────────────────────────────────────────────

def shap_card(shap_json) -> str:
    """Render the top-3 SHAP attributions as a compact HTML block."""
    if shap_json is None:
        return "<em style='color:#9ca3af'>No SHAP data</em>"
    try:
        items = shap_json if isinstance(shap_json, list) else json.loads(shap_json)
    except Exception:
        return "<em style='color:#9ca3af'>Parse error</em>"

    rows = []
    for item in items[:3]:
        feat = item.get("feature", "?")
        impact = item.get("impact", 0.0)
        sign = "+" if impact >= 0 else ""
        bar_colour = "#ef4444" if impact >= 0 else "#22c55e"
        bar_width = min(abs(impact) * 200, 100)  # scale for display
        rows.append(
            f'<div style="margin-bottom:4px">'
            f'  <span style="font-size:0.7rem;color:#374151">{feat}</span>'
            f'  <div style="background:#f3f4f6;border-radius:3px;height:6px;width:100%">'
            f'    <div style="background:{bar_colour};width:{bar_width:.0f}%;height:6px;border-radius:3px"></div>'
            f'  </div>'
            f'  <span style="font-size:0.65rem;color:{bar_colour}">{sign}{impact:.3f}</span>'
            f'</div>'
        )
    return "".join(rows)


# ── Layout ────────────────────────────────────────────────────────────────────

def render_header() -> None:
    st.markdown(
        """
        <h1 style="margin-bottom:0">
          &#x1F6E1; AI Risk Manager
          <span style="font-size:1rem;color:#6b7280;font-weight:400">
            &mdash; Live Audit Dashboard
          </span>
        </h1>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<p style='color:#9ca3af;font-size:0.8rem'>Cache TTL: {CACHE_TTL_SECS}s &bull; "
        f"Last refresh: {datetime.now().strftime('%H:%M:%S')}</p>",
        unsafe_allow_html=True,
    )


def render_kpi_row(stats: dict) -> None:
    """Four metric cards across the top."""
    total = stats.get("total_scored") or 0
    avg_s = stats.get("avg_score")
    allow = stats.get("allow_cod") or 0
    nudge = stats.get("nudge_prepay") or 0
    gate = stats.get("soft_gate_cod") or 0
    high_risk = stats.get("high_risk_count") or 0

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Scored", f"{total:,}")
    c2.metric("Avg Risk Score", f"{avg_s:.3f}" if avg_s is not None else "—")
    c3.metric(
        "High-Risk Orders",
        f"{high_risk:,}",
        delta=f"{high_risk/total*100:.1f}%" if total else None,
    )
    c4.metric(
        "Tier Mix",
        f"{allow} / {nudge} / {gate}",
        help="ALLOW_COD / NUDGE_PREPAY / SOFT_GATE_COD",
    )


def render_risk_gauges(stats: dict) -> None:
    """Gauge chart for risk score + pie chart for tier distribution."""
    col_gauge, col_pie = st.columns([1, 1])

    avg_score = float(stats.get("avg_score") or 0.0)

    # Gauge
    with col_gauge:
        st.markdown("#### Average Risk Score")
        fig = go.Figure(go.Indicator(
            mode="gauge+number+delta",
            value=avg_score,
            number={"valueformat": ".3f"},
            gauge={
                "axis": {"range": [0, 1], "tickformat": ".2f"},
                "bar": {"color": "#3b82f6"},
                "steps": [
                    {"range": [0, 0.5],  "color": "#dcfce7"},
                    {"range": [0.5, 0.75], "color": "#fef9c3"},
                    {"range": [0.75, 1],  "color": "#fee2e2"},
                ],
                "threshold": {
                    "line": {"color": "#ef4444", "width": 3},
                    "thickness": 0.75,
                    "value": 0.75,
                },
            },
            delta={"reference": 0.5, "valueformat": ".3f"},
        ))
        fig.update_layout(height=250, margin=dict(l=20, r=20, t=30, b=0))
        st.plotly_chart(fig, use_container_width=True)

    # Tier pie
    with col_pie:
        st.markdown("#### Tier Distribution")
        labels = ["ALLOW_COD", "NUDGE_PREPAY", "SOFT_GATE_COD"]
        values = [
            stats.get("allow_cod") or 0,
            stats.get("nudge_prepay") or 0,
            stats.get("soft_gate_cod") or 0,
        ]
        colours = [TIER_COLOURS[l] for l in labels]
        if sum(values) == 0:
            st.info("No data yet — submit some orders to see the distribution.")
        else:
            fig = px.pie(
                names=labels,
                values=values,
                color_discrete_sequence=colours,
                hole=0.45,
            )
            fig.update_layout(
                height=250,
                margin=dict(l=0, r=0, t=10, b=0),
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(fig, use_container_width=True)


def render_score_histogram(df: pd.DataFrame) -> None:
    """Score distribution histogram."""
    st.markdown("#### Score Distribution")
    if df.empty or "score" not in df.columns or df["score"].dropna().empty:
        st.info("No score data available yet.")
        return
    fig = px.histogram(
        df.dropna(subset=["score"]),
        x="score",
        nbins=20,
        color_discrete_sequence=["#3b82f6"],
        labels={"score": "Risk Score", "count": "Orders"},
    )
    fig.add_vline(
        x=0.5, line_dash="dash",
        line_color=TIER_COLOURS["NUDGE_PREPAY"],
        annotation_text="t_low=0.5",
    )
    fig.add_vline(
        x=0.75, line_dash="dash",
        line_color=TIER_COLOURS["SOFT_GATE_COD"],
        annotation_text="t_high=0.75",
    )
    fig.update_layout(height=220, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)


def render_timeseries(ts_df: pd.DataFrame) -> None:
    """Score trend sparkline over last 24 h."""
    st.markdown("#### Score Trend (last 24 h)")
    if ts_df.empty:
        st.info("No time-series data yet.")
        return
    fig = px.line(
        ts_df,
        x="bucket",
        y="avg_score",
        labels={"bucket": "Time", "avg_score": "Avg Risk Score"},
        color_discrete_sequence=["#8b5cf6"],
    )
    fig.add_hline(y=0.5, line_dash="dot", line_color=TIER_COLOURS["NUDGE_PREPAY"])
    fig.add_hline(y=0.75, line_dash="dot", line_color=TIER_COLOURS["SOFT_GATE_COD"])
    fig.update_layout(height=200, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig, use_container_width=True)


def render_shap_cards(df: pd.DataFrame) -> None:
    """Render SHAP importance cards for the most-recent visible orders."""
    st.markdown("#### SHAP Feature Importance (recent orders)")

    if df.empty or "shap_values_json" not in df.columns:
        st.info("No SHAP data available yet.")
        return

    sample = df.head(6)
    cols = st.columns(3)

    for idx, (_, row) in enumerate(sample.iterrows()):
        col = cols[idx % 3]
        tier = row.get("tier") or "unknown"
        score = row.get("score")
        order_id = str(row.get("order_id", "?"))
        shap_json = row.get("shap_values_json")

        tier_colour = TIER_COLOURS.get(tier, TIER_COLOURS["unknown"])
        score_str = f"{score:.3f}" if score is not None else "—"
        short_id = (order_id[:14] + "…") if len(order_id) > 14 else order_id

        with col:
            st.markdown(
                f"""
<div style="border:1px solid #e5e7eb;border-left:4px solid {tier_colour};
border-radius:8px;padding:10px 12px;margin-bottom:10px;background:#fafafa">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
    <span style="font-weight:600;font-size:0.8rem;color:#374151">{short_id}</span>
    <span style="background:{tier_colour};color:white;padding:1px 6px;border-radius:4px;
    font-size:0.65rem;font-weight:700">{tier.replace("_"," ")}</span>
  </div>
  <div style="font-size:0.75rem;color:#6b7280;margin-bottom:6px">
    Score: <strong style="color:#111827">{score_str}</strong>
  </div>
  {shap_card(shap_json)}
</div>
                """,
                unsafe_allow_html=True,
            )


def render_audit_feed(df: pd.DataFrame) -> None:
    """Render the live audit log feed."""
    st.markdown("#### Live Audit Feed")

    if df.empty:
        st.info(
            "No scored orders yet. "
            "Submit an order via `POST /v1/orders/score` to see it here."
        )
        return

    display_df = df.copy()

    if "created_at" in display_df.columns:
        display_df["created_at"] = pd.to_datetime(
            display_df["created_at"], utc=True
        ).dt.strftime("%Y-%m-%d %H:%M:%S")

    if "score" in display_df.columns:
        display_df["score"] = display_df["score"].round(4)

    display_df = display_df.rename(columns={
        "event_id": "Event ID",
        "order_id": "Order ID",
        "score": "Score",
        "tier": "Tier",
        "action": "Action",
        "created_at": "Scored At",
        "explanation_text": "LLM Explanation",
        "explanation_status": "LLM Status",
    })

    columns_to_show = [
        "Event ID", "Order ID", "Score", "Tier",
        "Action", "Scored At", "LLM Status", "LLM Explanation",
    ]
    columns_to_show = [c for c in columns_to_show if c in display_df.columns]

    st.dataframe(
        display_df[columns_to_show],
        use_container_width=True,
        height=320,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score",
                min_value=0.0,
                max_value=1.0,
                format="%.3f",
            ),
            "LLM Explanation": st.column_config.TextColumn(
                "LLM Explanation", width="large"
            ),
        },
        hide_index=True,
    )


def render_sidebar(stats: dict, llm_breakdown: dict) -> None:
    """Sidebar: system health, thresholds, LLM stats."""
    with st.sidebar:
        st.markdown("## System Health")

        # Thresholds
        try:
            thresh_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "config", "thresholds.json",
            )
            with open(thresh_path) as f:
                thresh = json.load(f)
            t_low = thresh.get("t_low", "?")
            t_high = thresh.get("t_high", "?")
        except Exception:
            t_low = t_high = "?"

        st.markdown(
            f"""
**Production Thresholds**
- `t_low` = `{t_low}`
- `t_high` = `{t_high}`

Tiers:
- ALLOW\\_COD: score &lt; t\\_low
- NUDGE\\_PREPAY: t\\_low &le; score &lt; t\\_high
- SOFT\\_GATE\\_COD: score &ge; t\\_high
            """
        )

        st.divider()

        st.markdown("**Database**")
        total = stats.get("total_scored") or 0
        st.metric("audit_log rows", f"{total:,}")

        st.divider()

        st.markdown("**LLM Explanations**")
        if llm_breakdown:
            for status_key, cnt in llm_breakdown.items():
                icon = (
                    "complete" if status_key == "complete"
                    else "fallback" if status_key == "fallback"
                    else "pending"
                )
                st.metric(f"{icon}: {status_key}", f"{cnt:,}")
        else:
            st.caption("No explanations yet")

        st.divider()

        st.markdown(f"**Cache TTL:** `{CACHE_TTL_SECS}s`")
        st.caption(
            "Set `DASHBOARD_CACHE_TTL` env var to change.\n\n"
            "Data refreshes automatically on each Streamlit re-run."
        )

        if st.button("Force Refresh"):
            st.cache_data.clear()
            st.rerun()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title=PAGE_TITLE,
        page_icon="shield",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    feed_limit = st.sidebar.slider(
        "Feed rows", min_value=10, max_value=200, value=DEFAULT_FEED_LIMIT, step=10,
        help="Max rows shown in the live audit feed",
    )
    auto_refresh = st.sidebar.checkbox(
        "Auto-refresh (30 s)", value=False,
        help="Reloads the page every 30 seconds for continuous updates",
    )

    with st.spinner("Fetching latest data..."):
        stats = load_summary_stats()
        audit_df = load_audit_feed(limit=feed_limit)
        llm_breakdown = load_llm_breakdown()
        ts_df = load_score_timeseries(hours=24)

    render_sidebar(stats, llm_breakdown)
    render_header()

    if not stats:
        st.error(
            "Could not connect to Postgres. "
            "Check `DATABASE_URL_SYNC` in your `.env` and that the DB is running."
        )
        st.stop()

    render_kpi_row(stats)
    st.divider()

    render_risk_gauges(stats)

    col_hist, col_ts = st.columns([1, 1])
    with col_hist:
        render_score_histogram(audit_df)
    with col_ts:
        render_timeseries(ts_df)

    st.divider()
    render_shap_cards(audit_df)

    st.divider()
    render_audit_feed(audit_df)

    if auto_refresh:
        import time
        time.sleep(30)
        st.rerun()


if __name__ == "__main__":
    main()
