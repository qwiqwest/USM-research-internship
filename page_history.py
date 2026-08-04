"""History page — past inspection records. Real data only, no mock rows."""

from datetime import datetime

import streamlit as st

from common import page_header, kpi_card, render_board_image, get_routing_info, missing_components_list


def render(df):
    page_header("History", "Past inspection records", "📊")

    total = len(df)
    passes = int((df["verdict"] == "PASS").sum())
    fails = total - passes
    yield_rate = (passes / total * 100) if total else 0

    st.markdown(
        '<div class="kpi-row">'
        + kpi_card("Total Inspected", f"{total}", "📦")
        + kpi_card("Passed", f"{passes}", "✅")
        + kpi_card("Failed", f"{fails}", "⚠️")
        + kpi_card("Line Yield", f"{yield_rate:.1f}%", "📈", accent=True)
        + "</div>",
        unsafe_allow_html=True,
    )

    if total == 0:
        st.info(
            "No inspections yet. This table only shows real results published to "
            "`semiconductor/inspection/result` — trigger the conveyor's IR sensor "
            "with camera_inference.py and bridge.py running to see one appear here."
        )
        return

    latest = df.iloc[0]

    with st.container(border=True):
        st.markdown("**Most Recent Board**")
        latest_col1, latest_col2 = st.columns([1, 2])
        with latest_col1:
            render_board_image(latest, use_container_width=True)
        with latest_col2:
            st.markdown(f'**Board ID:** {latest["board_id"]}')
            st.markdown(f'**Serial:** <span class="mono">{latest["serial_number"]}</span>', unsafe_allow_html=True)
            if latest["verdict"] == "PASS":
                st.success(f"VERDICT: PASS — {get_routing_info('PASS', '-')}")
            else:
                st.error(f"VERDICT: FAIL ({latest['fail_reason']}) — {get_routing_info('FAIL', latest['fail_reason'])}")

            missing = missing_components_list(latest["detected_components"])
            if missing:
                st.caption(f"Missing: {', '.join(missing)}")

    with st.container(border=True):
        with st.expander("📈 Charts", expanded=False):
            chart_col1, chart_col2 = st.columns(2)
            with chart_col1:
                st.caption("Pass / Fail by day")
                trend_df = df.copy()
                trend_df["date"] = trend_df["timestamp"].dt.date
                trend = trend_df.groupby(["date", "verdict"]).size().unstack(fill_value=0)
                st.bar_chart(trend)
            with chart_col2:
                st.caption("Fail reasons")
                fail_df = df[df["verdict"] == "FAIL"]
                if not fail_df.empty:
                    st.bar_chart(fail_df["fail_reason"].value_counts())
                else:
                    st.info("No failures recorded yet.")

        with st.expander("🔍 Filters"):
            f1, f2, f3 = st.columns(3)
            with f1:
                verdict_filter = st.multiselect("Verdict", ["PASS", "FAIL"], default=["PASS", "FAIL"])
            with f2:
                reason_options = sorted(df["fail_reason"].unique().tolist())
                reason_filter = st.multiselect("Fail Reason", reason_options, default=reason_options)
            with f3:
                search_query = st.text_input("Search Board ID / Serial")

        filtered = df[df["verdict"].isin(verdict_filter) & df["fail_reason"].isin(reason_filter)]
        if search_query:
            filtered = filtered[
                filtered["board_id"].str.contains(search_query, case=False)
                | filtered["serial_number"].str.contains(search_query, case=False)
            ]

        st.markdown("**All Records**")
        display_df = filtered[[
            "board_id", "serial_number", "timestamp", "verdict", "fail_reason", "routing",
        ]].copy()
        display_df["timestamp"] = display_df["timestamp"].dt.strftime("%d %b, %H:%M")
        display_df.columns = ["Board ID", "Serial", "Time", "Verdict", "Reason", "Routed To"]
        st.dataframe(display_df, use_container_width=True, hide_index=True, height=300)

        st.download_button(
            "📥 Export to CSV",
            data=filtered.drop(columns=["detected_components"]).to_csv(index=False).encode("utf-8"),
            file_name=f"AOI_Inspection_Logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )
