"""Live Inspection page — continuous camera preview + component checklist,
fed by camera_inference.py over MQTT."""

import streamlit as st

from common import page_header, EXPECTED_COMPONENTS


def render():
    page_header("Live Inspection", "Read a board's serial number from a photo", "🔍")

    with st.container(border=True):
        st.markdown("**Live Board Result**")
        st.caption("One result per board: what camera_inference.py currently sees, checked against the full expected component list — not treated as separate pieces.")
        if st.session_state.live_camera_frame:
            img_col, checklist_col = st.columns([1.3, 1])
            with img_col:
                st.markdown(
                    f'<img class="live-frame" src="data:image/jpeg;base64,{st.session_state.live_camera_frame}">',
                    unsafe_allow_html=True,
                )
                st.caption(f"Last updated: {st.session_state.live_camera_ts}")

            with checklist_col:
                detected_now = st.session_state.live_camera_detections
                missing_now = [c for c in EXPECTED_COMPONENTS if c not in detected_now]

                items_html = ""
                for component in EXPECTED_COMPONENTS:
                    found = component in detected_now
                    icon = "✅" if found else "❌"
                    label = component.replace("_", " ")
                    items_html += f'<div class="checklist-item">{icon} {label}</div>'

                st.markdown(
                    f'<div class="checklist-box">'
                    f'<div style="font-weight:600;margin-bottom:8px;">Component checklist</div>'
                    f'<div class="checklist-grid">{items_html}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if missing_now:
                    st.caption(f"{len(missing_now)} of {len(EXPECTED_COMPONENTS)} not currently visible — normal if the board isn't fully in frame yet.")
                else:
                    st.caption("All expected components currently visible.")
        else:
            st.info("Waiting for camera_inference.py to publish a frame — make sure it's running and connected to the same MQTT broker.")
