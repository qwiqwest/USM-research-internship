"""Manual Capture page — take a photo or upload one, run the same
detection model + OCR directly from the dashboard, and push a real
record into History/Dashboard. Works even if the conveyor, bridge.py,
or camera_inference.py aren't connected."""

import streamlit as st
from PIL import Image

from common import (
    page_header, REQUESTS_AVAILABLE, OCR_AVAILABLE,
    run_manual_detection, read_serial_number, build_manual_record, add_history_row,
)


def render():
    page_header("Manual Capture", "Test the full pipeline without the conveyor connected", "📤")

    with st.container(border=True):
        st.markdown("**Manual Capture / Upload**")
        st.caption(
            "Runs the same detection model (and optionally OCR) on a single photo and "
            "adds a real record to History/Dashboard — use this when the conveyor, "
            "bridge.py, or camera_inference.py aren't connected, so you can still test "
            "the full pipeline."
        )

        if not REQUESTS_AVAILABLE:
            st.warning("`requests` isn't installed yet.\n\nRun this once:\n`pip install requests`")
        if not OCR_AVAILABLE:
            st.warning("OCR isn't installed yet — the serial number field will be left as UNREADABLE.\n\nRun:\n`pip install easyocr opencv-python-headless`")

        source = st.radio("Image source", ["📷 Camera", "📁 Upload file"], horizontal=True, key="manual_source")

        manual_image = None
        if source == "📷 Camera":
            cam_file = st.camera_input("Take a photo of the board", key="manual_camera_input")
            if cam_file is not None:
                manual_image = Image.open(cam_file)
        else:
            up_file = st.file_uploader("Upload a board photo", type=["jpg", "jpeg", "png"], key="manual_upload_input")
            if up_file is not None:
                manual_image = Image.open(up_file)

        manual_board_id = st.text_input("Board ID (optional — auto-generated if left blank)", key="manual_board_id")

        run_ocr = False
        if OCR_AVAILABLE:
            run_ocr = st.checkbox(
                "Also run OCR (serial number) — slower",
                value=False,
                key="manual_run_ocr",
            )

        if manual_image is not None:
            st.image(manual_image, caption="Captured photo", width=320)

            if st.button("▶️ Run Inspection", type="primary", disabled=not REQUESTS_AVAILABLE):
                spinner_text = "Running detection + OCR..." if run_ocr else "Running detection..."
                with st.spinner(spinner_text):
                    annotated, predictions = run_manual_detection(manual_image)
                    serial_text, ocr_conf = "SKIPPED", 0.0
                    if OCR_AVAILABLE and run_ocr:
                        serial_text, ocr_conf, _ = read_serial_number(manual_image)

                if annotated is None:
                    st.session_state.manual_last_result = {
                        "error": st.session_state.get("_manual_detect_error", "unknown error")
                    }
                else:
                    record = build_manual_record(annotated, predictions, serial_text, ocr_conf, manual_board_id)
                    add_history_row(record)
                    st.session_state.manual_last_result = {"error": None, "annotated": annotated, "record": record}

        # Rendered from session_state (not inline in the button block) so the
        # result stays visible across reruns instead of disappearing the
        # instant the page reruns (e.g. the very next autorefresh tick).
        result = st.session_state.get("manual_last_result")
        if result:
            if result["error"]:
                st.error(f"Detection call failed: {result['error']}")
            else:
                record = result["record"]
                if record["verdict"] == "PASS":
                    st.success(f"VERDICT: PASS — {record['routing']}")
                else:
                    st.error(f"VERDICT: FAIL ({record['fail_reason']}) — {record['routing']}")
                st.image(result["annotated"], caption="Detected components", width=320)
                st.caption(f"Serial read: {record['serial_number']}  ·  Board ID: {record['board_id']}")
                st.caption("Added to History and Dashboard KPIs.")