"""Dashboard (landing) page — KPIs, trend, recent scans, yield gauge."""

from datetime import datetime

import streamlit as st

from common import page_header, kpi_card, status_pill, gauge_svg


def render(df):
    page_header("Dashboard", "Live overview of the inspection line", "🏠")

    total = len(df)
    passes = int((df["verdict"] == "PASS").sum())
    fails = total - passes
    yield_rate = (passes / total * 100) if total else 0

    st.markdown(
        '<div class="kpi-row">'
        + kpi_card("Total Inspected", f"{total}", "📦", accent=True)
        + kpi_card("Passed", f"{passes}", "✅")
        + kpi_card("Failed", f"{fails}", "⚠️")
        + kpi_card("Line Yield", f"{yield_rate:.1f}%", "📈")
        + "</div>",
        unsafe_allow_html=True,
    )

    main_col, side_col = st.columns([2, 1])

    with main_col:
        with st.container(border=True):
            st.markdown("**Inspection Trend**")
            st.caption("Pass / fail volume by day")
            trend_df = df.copy()
            trend_df["date"] = trend_df["timestamp"].dt.date
            trend = trend_df.groupby(["date", "verdict"]).size().unstack(fill_value=0)
            st.bar_chart(trend, height=260)

        with st.container(border=True):
            st.markdown("**Recent Scans**")
            if df.empty:
                st.info("No inspections yet — waiting for the first real result over MQTT.")
            else:
                rows_html = ""
                for _, r in df.head(6).iterrows():
                    dot_cls = "dot-pass" if r["verdict"] == "PASS" else "dot-fail"
                    if r.get("manual"):
                        live_badge = '<span class="live-badge" style="color:var(--blue);background:#DBEAFE;">● MANUAL</span>'
                    elif r.get("live"):
                        live_badge = '<span class="live-badge">● LIVE</span>'
                    else:
                        live_badge = ""
                    rows_html += (
                        '<div class="scan-row">'
                        f'<div class="dot {dot_cls}"></div>'
                        '<div class="scan-info">'
                        f'<span class="scan-id">{r["board_id"]}<span class="scan-serial mono">{r["serial_number"]}</span>{live_badge}</span>'
                        f'<div class="scan-meta">{r["timestamp"].strftime("%d %b, %H:%M")} · {r["routing"]}</div>'
                        '</div>'
                        f'<div>{status_pill(r["verdict"])}</div>'
                        '</div>'
                    )
                st.markdown(rows_html, unsafe_allow_html=True)

    with side_col:
        with st.container(border=True):
            st.markdown(
                f'<div style="display:flex;justify-content:center;">{gauge_svg(yield_rate)}</div>',
                unsafe_allow_html=True,
            )

        with st.container(border=True):
            st.markdown("**Dashboard Session**")
            elapsed = datetime.now() - st.session_state.session_start
            hrs, rem = divmod(int(elapsed.total_seconds()), 3600)
            mins, secs = divmod(rem, 60)
            st.markdown(
                f'<div class="mono" style="font-size:26px;font-weight:700;color:var(--text);">'
                f'{hrs:02d}:{mins:02d}:{secs:02d}</div>',
                unsafe_allow_html=True,
            )
            st.caption("Time since this dashboard was opened — not yet linked to real machine uptime.")
