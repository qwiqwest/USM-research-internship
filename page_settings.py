"""Settings page — technical config, kept out of the main view."""

import streamlit as st

from common import page_header, empty_history_df


def render():
    page_header("Settings", "System configuration & reference info", "⚙️")

    with st.container(border=True):
        st.markdown("**Clear History**")
        st.caption("Wipes all recorded inspections from this session (real data only — there's no mock data to reset).")
        if st.button("🗑️ Clear all history"):
            st.session_state.history_df = empty_history_df()
            st.rerun()
