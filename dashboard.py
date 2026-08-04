"""
PCBA Inspection Dashboard — entry point
--------------------------------------------------
This file is now just the shell: page config, CSS, session state, the
sidebar nav, and MQTT/autorefresh wiring. Each page's actual content
lives in its own file so this doesn't balloon back into one giant
script:

  common.py               -> config, styling, MQTT, OCR, manual-detection
                              logic shared by every page.
  page_dashboard.py        -> 🏠 Dashboard: KPIs, trend, yield gauge, recent scans.
  page_live_inspection.py  -> 🔍 Live Inspection: continuous camera feed +
                              component checklist from camera_inference.py.
  page_manual_capture.py   -> 📤 Manual Capture: take/upload a photo, run
                              detection + OCR directly, push a record into
                              History — works without the conveyor connected.
  page_history.py          -> 📊 History: past inspection records, charts,
                              filters, CSV export. Real data only.
  page_settings.py         -> ⚙️ Settings: clear history.

Run with:
    streamlit run dashboard.py

First-time setup (one-time):
    pip install streamlit pandas pillow opencv-python-headless easyocr paho-mqtt streamlit-autorefresh requests
    (easyocr's first run will download its English text-detection model —
    this needs an internet connection once, then it works offline.)

MQTT
----
Listens on `semiconductor/inspection/result` for JSON payloads shaped like:

    {"board_id": "BRD-1042", "serial_number": "SN-000123",
     "verdict": "PASS", "fail_reason": "-",
     "detected_components": {"ethernet_port": 1, "usb_host": 1, ...},
     "ocr_confidence": 0.94, "defect_confidence": 0.91}

Any publisher can feed this — camera_inference.py today, a locally-trained
model later. Stop/Resume buttons publish to `semiconductor/conveyor/cmd`.
"""

import streamlit as st

import common
import page_dashboard
import page_live_inspection
import page_manual_capture
import page_history
import page_settings

# ----------------------------------------------------------------------
# PAGE CONFIG + STYLE
# ----------------------------------------------------------------------
st.set_page_config(
    page_title="AOIVision — PCBA Inspection",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(common.PAGE_CSS, unsafe_allow_html=True)

# ----------------------------------------------------------------------
# SESSION STATE + MQTT + AUTOREFRESH
# ----------------------------------------------------------------------
common.init_session_state()

if common.MQTT_AVAILABLE:
    common.start_mqtt_client()
    common.drain_mqtt_inbox()

# Keep the page refreshing on its own so live MQTT rows show up without a
# manual reload — only on the pages that actually need live polling, so it
# doesn't fight with camera_input/file_uploader/buttons on other pages.
if common.AUTOREFRESH_AVAILABLE and st.session_state.page in ("Live Inspection"):
    common.st_autorefresh(interval=250, key="mqtt_autorefresh")

df = st.session_state.history_df

# ----------------------------------------------------------------------
# SIDEBAR — brand, nav, machine status
# ----------------------------------------------------------------------
st.sidebar.markdown(
    '<div class="brand"><span class="brand-icon">🔬</span>'
    '<span class="brand-text">AOI<span class="brand-accent">Vision</span></span></div>',
    unsafe_allow_html=True,
)

st.sidebar.markdown('<div class="nav-label">Navigation</div>', unsafe_allow_html=True)

NAV_ITEMS = [("🏠", "Dashboard"), ("🔍", "Live Inspection"), ("📤", "Manual Capture"), ("📊", "History"), ("⚙️", "Settings")]
for icon, name in NAV_ITEMS:
    is_active = st.session_state.page == name
    if st.sidebar.button(f"{icon}  {name}", key=f"nav_{name}", use_container_width=True,
                          type="primary" if is_active else "secondary"):
        st.session_state.page = name
        st.rerun()

st.sidebar.divider()
st.sidebar.markdown('<div class="nav-label">Machine Status</div>', unsafe_allow_html=True)

if st.session_state.conveyor_running:
    st.sidebar.success("Conveyor: RUNNING")
else:
    st.sidebar.error("Conveyor: STOPPED")

if not common.MQTT_AVAILABLE:
    st.sidebar.warning("MQTT isn't installed yet.\n\nRun this once:\n`pip install paho-mqtt`")
elif st.session_state.get("_mqtt_connect_error"):
    st.sidebar.error(f"MQTT broker unreachable:\n{st.session_state['_mqtt_connect_error']}")
else:
    st.sidebar.caption(f"MQTT: connected to {common.MQTT_BROKER}:{common.MQTT_PORT}")

col_btn1, col_btn2 = st.sidebar.columns(2)
with col_btn1:
    if st.button("🛑 Stop", use_container_width=True):
        common.publish_conveyor_cmd("stop")
with col_btn2:
    if st.button("▶️ Resume", use_container_width=True):
        common.publish_conveyor_cmd("resume")

if not common.OCR_AVAILABLE:
    st.sidebar.warning(
        "OCR isn't installed yet.\n\n"
        "Run this once:\n"
        "`pip install easyocr opencv-python-headless`"
    )

# ----------------------------------------------------------------------
# ROUTE TO THE SELECTED PAGE
# ----------------------------------------------------------------------
page = st.session_state.page

if page == "Dashboard":
    page_dashboard.render(df)
elif page == "Live Inspection":
    page_live_inspection.render()
elif page == "Manual Capture":
    page_manual_capture.render()
elif page == "History":
    page_history.render(df)
elif page == "Settings":
    page_settings.render()
