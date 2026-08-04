"""
Shared config, helpers, MQTT, OCR, and manual-detection logic used by
every page. Nothing in here renders a full page — that lives in
dashboard.py + the page_*.py files. Keeping this split means each page
file only has to think about its own UI, not the plumbing underneath.
"""

import base64
import json
import queue
import re
import math
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
from PIL import Image

# ----------------------------------------------------------------------
# OPTIONAL IMPORTS
# The dashboard still runs (History/Settings pages work fine, mock data
# still shows) even if these aren't installed yet.
# ----------------------------------------------------------------------
try:
    import cv2
    import easyocr
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import paho.mqtt.client as mqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

try:
    from streamlit_autorefresh import st_autorefresh
    AUTOREFRESH_AVAILABLE = True
except ImportError:
    AUTOREFRESH_AVAILABLE = False

# ----------------------------------------------------------------------
# MQTT CONFIG — change these to match your broker / ESP32 setup
# ----------------------------------------------------------------------
MQTT_BROKER = "localhost"          # <-- set to your broker's IP
MQTT_PORT = 1883
TOPIC_RESULT = "semiconductor/inspection/result"
TOPIC_CMD = "semiconductor/conveyor/cmd"
TOPIC_STATUS = "semiconductor/conveyor/status"
TOPIC_CAMERA_LIVE = "semiconductor/camera/live"

# ----------------------------------------------------------------------
# ROBOFLOW CONFIG — used ONLY for the manual capture/upload tool, so a
# result can still be produced (and land in History) when the real
# conveyor/camera hardware isn't connected. Keep these in sync with
# camera_inference.py's config — same model, same threshold.
# ----------------------------------------------------------------------
ROBOFLOW_API_KEY = "Mv5CfziDdtMzclAQjaep"
MODEL_ID = "nurs-workspace-yquat/board-oqvfa-1-yolo11n-t2"
CONFIDENCE_THRESHOLD = 0.5
ROBOFLOW_API_URL = f"https://detect.roboflow.com/{MODEL_ID}"
INFER_MAX_DIM = 640

# ----------------------------------------------------------------------
# VISUAL IDENTITY
# Palette grounded in the subject (PCB soldermask green + circuit-trace
# blue) rather than a generic SaaS look. Sora for headings (technical,
# geometric), Inter for body text, JetBrains Mono for serial numbers /
# data — real inspection readouts use monospace so digits stay aligned
# and scannable, the same way a multimeter or terminal would show them.
# ----------------------------------------------------------------------
ACCENT = "#0F8B6C"
ACCENT_DARK = "#0B6E56"
BLUE = "#2563EB"
DANGER = "#DC2626"
WARN = "#D97706"

PAGE_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;600&display=swap');

:root {{
    --accent: {ACCENT};
    --accent-dark: {ACCENT_DARK};
    --blue: {BLUE};
    --danger: {DANGER};
    --warn: {WARN};
    --text: #101828;
    --muted: #667085;
    --surface: #FFFFFF;
    --border: #EAECEF;
}}

html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
h1, h2, h3 {{ font-family: 'Sora', sans-serif !important; }}
.mono {{ font-family: 'JetBrains Mono', monospace; }}

.block-container {{ padding-top: 2rem; padding-bottom: 3rem; max-width: 1200px; }}

[data-testid="stSidebar"] {{ background: var(--surface); border-right: 1px solid var(--border); }}
[data-testid="stSidebar"] .block-container {{ padding-top: 1.5rem; }}

.brand {{ display:flex; align-items:center; gap:10px; margin-bottom:22px; }}
.brand-icon {{ font-size:24px; }}
.brand-text {{ font-family:'Sora',sans-serif; font-weight:700; font-size:19px; color:var(--text); }}
.brand-accent {{ color: var(--accent); }}

.nav-label {{ font-size:11px; font-weight:700; letter-spacing:.06em; color:var(--muted);
              margin:14px 0 8px 2px; text-transform:uppercase; }}

.stButton>button {{ border-radius:10px; font-weight:600; }}

div[data-testid="stVerticalBlockBorderWrapper"] {{
    border-radius:16px !important;
    border-color: var(--border) !important;
    box-shadow: 0 1px 2px rgba(16,24,40,0.04), 0 1px 3px rgba(16,24,40,0.05);
}}

.page-header {{ display:flex; align-items:center; gap:14px; margin-bottom:22px; }}
.page-header-icon {{ font-size:30px; }}
.page-title {{ font-family:'Sora',sans-serif; font-size:25px; font-weight:700; color:var(--text); line-height:1.2; }}
.page-subtitle {{ font-size:13.5px; color:var(--muted); margin-top:2px; }}

.kpi-row {{ display:flex; gap:16px; margin-bottom:20px; flex-wrap:wrap; }}
.kpi-card {{ flex:1; min-width:160px; background:var(--surface); border-radius:16px; padding:20px 22px;
             box-shadow:0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06); border:1px solid var(--border); }}
.kpi-card.accent {{ background:linear-gradient(135deg,var(--accent),var(--accent-dark)); color:#fff; border:none; }}
.kpi-icon {{ font-size:20px; margin-bottom:10px; opacity:.85; }}
.kpi-value {{ font-family:'Sora',sans-serif; font-size:28px; font-weight:700; line-height:1; }}
.kpi-label {{ font-size:12.5px; color:var(--muted); margin-top:6px; }}
.kpi-card.accent .kpi-label {{ color:rgba(255,255,255,.85); }}

.pill {{ padding:3px 11px; border-radius:999px; font-size:11.5px; font-weight:700; letter-spacing:.02em; }}
.pill-pass {{ background:#DCFCE7; color:#15803D; }}
.pill-fail {{ background:#FEE2E2; color:#B91C1C; }}

.scan-row {{ display:flex; align-items:center; gap:12px; padding:11px 2px; border-bottom:1px solid #F2F4F7; }}
.scan-row:last-child {{ border-bottom:none; }}
.dot {{ width:8px; height:8px; border-radius:50%; flex-shrink:0; }}
.dot-pass {{ background:#22C55E; }}
.dot-fail {{ background:#EF4444; }}
.scan-info {{ flex:1; min-width:0; }}
.scan-id {{ font-weight:600; font-size:13.5px; color:var(--text); }}
.scan-serial {{ margin-left:8px; color:var(--muted); font-size:12px; }}
.scan-meta {{ font-size:12px; color:var(--muted); margin-top:2px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}

.result-card {{ padding:22px; border-radius:14px; text-align:center; }}
.result-pass {{ background:#ECFDF5; color:#065F46; }}
.result-fail {{ background:#FEF2F2; color:#991B1B; }}
.result-label {{ font-size:13px; opacity:.85; }}
.result-value {{ font-family:'JetBrains Mono',monospace; font-size:26px; font-weight:700; margin:4px 0; }}
.result-sub {{ font-size:12.5px; opacity:.75; }}

.live-badge {{ display:inline-flex; align-items:center; gap:6px; font-size:11.5px; font-weight:700;
               color:#15803D; background:#DCFCE7; padding:3px 10px; border-radius:999px; margin-left:8px; }}

.live-frame {{ width:100%; height:380px; object-fit:cover; border-radius:12px; background:#000; display:block; }}
.checklist-box {{ height:380px; overflow-y:auto; border:1px solid var(--border); border-radius:12px;
                   padding:12px 14px; }}
.checklist-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:4px 10px; }}
.checklist-item {{ display:flex; align-items:center; gap:6px; font-size:13px; color:var(--text);
                    padding:3px 0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
</style>
"""


def page_header(title: str, subtitle: str, icon: str = "🔬"):
    st.markdown(
        f'<div class="page-header"><div class="page-header-icon">{icon}</div>'
        f'<div><div class="page-title">{title}</div>'
        f'<div class="page-subtitle">{subtitle}</div></div></div>',
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, icon: str = "📦", accent: bool = False) -> str:
    cls = "kpi-card accent" if accent else "kpi-card"
    return f'<div class="{cls}"><div class="kpi-icon">{icon}</div><div class="kpi-value">{value}</div><div class="kpi-label">{label}</div></div>'


def status_pill(verdict: str) -> str:
    cls = "pill-pass" if verdict == "PASS" else "pill-fail"
    return f'<span class="pill {cls}">{verdict}</span>'


def gauge_svg(percent: float, label: str = "Line Yield", size: int = 190, accent: str = ACCENT) -> str:
    percent = max(0.0, min(100.0, percent))
    radius = size / 2 - 20
    cx = cy = size / 2
    circumference = 2 * math.pi * radius
    offset = circumference * (1 - percent / 100)

    ticks = []
    for i in range(24):
        angle = math.radians(i * 15)
        x1 = cx + (radius + 8) * math.cos(angle)
        y1 = cy + (radius + 8) * math.sin(angle)
        x2 = cx + (radius + 13) * math.cos(angle)
        y2 = cy + (radius + 13) * math.sin(angle)
        ticks.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#E4E7EC" stroke-width="2"/>')

    return f'''
    <svg width="{size}" height="{size}" viewBox="0 0 {size} {size}">
      {"".join(ticks)}
      <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="#EEF1F4" stroke-width="11"/>
      <circle cx="{cx}" cy="{cy}" r="{radius}" fill="none" stroke="{accent}" stroke-width="11"
        stroke-dasharray="{circumference:.1f}" stroke-dashoffset="{offset:.1f}"
        stroke-linecap="round" transform="rotate(-90 {cx} {cy})"/>
      <text x="{cx}" y="{cy - 2}" text-anchor="middle" font-family="Sora, sans-serif" font-size="30" font-weight="700" fill="#101828">{percent:.0f}%</text>
      <text x="{cx}" y="{cy + 20}" text-anchor="middle" font-family="Inter, sans-serif" font-size="12" fill="#667085">{label}</text>
    </svg>
    '''


EXPECTED_COMPONENTS = {
    "ethernet_port": 1,
    "ethernet_phy": 1,
    "rs232": 1,
    "rs232_port": 1,
    "usb_host": 1,
    "usb_client": 1,
    "spiflash": 1,
    "spiflash_port": 1,
    "gpio_expander": 1,
    "level_shifter": 1,
    "voltage_regulator": 1,
    "processor": 1,
    "ram": 1,
    "power_outlet": 1,
    "microsd": 1,
    "jtag": 1,
    "reboot_button": 1,
    "serial_label": 1,      # the printed label region — detected as part of
                             # the board like any other component, not carved
                             # out separately. The OCR-read text itself still
                             # lives in the record's own `serial_number` field
                             # (e.g. "SN-000123") — this class just confirms
                             # the label area was actually visible/detected.
}
BOARD_TYPE = "Intel Galileo Gen 2"

# Non-"missing" defect categories — kept generic since they can apply to
# any component, not tied to a specific one. "missing_<component>" fail
# reasons are generated dynamically from EXPECTED_COMPONENTS instead of
# needing one hardcoded entry per class (16+ components would be unwieldy).
ROUTING_MAP = {
    "PASS": "✅ Goes to Bin A — Good Units",
    "scratch": "↩️ Goes to Bin B — Reject (surface scratch)",
    "burn_mark": "↩️ Goes to Bin B — Reject (burn mark)",
    "misaligned": "↩️ Goes to Bin B — Reject (misaligned component)",
    "serial_unreadable": "🔁 Sent to manual re-check station (serial unreadable)",
}


def get_routing_info(verdict: str, fail_reason: str) -> str:
    if verdict == "PASS":
        return ROUTING_MAP["PASS"]
    if fail_reason.startswith("missing_"):
        component = fail_reason.replace("missing_", "").replace("_", " ")
        return f"↩️ Goes to Bin B — Reject (missing {component})"
    return ROUTING_MAP.get(fail_reason, "↩️ Goes to Bin B — Reject")


# ----------------------------------------------------------------------
# MQTT — background subscriber + thread-safe inbox
#
# Streamlit reruns the whole script on every interaction, so we can't just
# call client.loop_forever() inline. Instead: start ONE background MQTT
# client (cached so it only starts once per server process), have its
# on_message callback drop parsed records into a plain thread-safe Queue,
# then drain that queue into session_state at the top of every rerun.
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_mqtt_inbox():
    """A queue shared by the background MQTT thread and the Streamlit script."""
    return queue.Queue()


@st.cache_resource(show_spinner=False)
def start_mqtt_client():
    """
    Starts the MQTT client exactly once per server process (cache_resource
    persists across reruns/sessions). Returns the client so buttons can
    publish on it later.
    """
    if not MQTT_AVAILABLE:
        return None

    inbox = get_mqtt_inbox()

    def on_connect(client, userdata, flags, rc, properties=None):
        client.subscribe(TOPIC_RESULT)
        client.subscribe(TOPIC_STATUS)
        client.subscribe(TOPIC_CAMERA_LIVE)

    def on_message(client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return  # ignore malformed messages instead of crashing the listener
        inbox.put((msg.topic, payload))

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()  # runs networking in its own background thread
    except Exception as e:
        st.session_state["_mqtt_connect_error"] = str(e)
        return None

    return client


def record_from_mqtt_payload(payload: dict) -> dict:
    """
    Normalizes an incoming MQTT JSON payload into the same row shape used
    everywhere else, so nothing downstream (KPIs, charts, tables) needs to
    know whether a row came from MQTT or the manual tool. Missing fields
    fall back to sensible defaults instead of crashing — a partial payload
    from an early test script shouldn't break the page.
    """
    verdict = payload.get("verdict", "PASS")
    fail_reason = payload.get("fail_reason", "-")
    detected = payload.get("detected_components", dict(EXPECTED_COMPONENTS))
    return {
        "board_id": payload.get("board_id", f"BRD-LIVE-{datetime.now().strftime('%H%M%S')}"),
        "serial_number": payload.get("serial_number", "UNREADABLE"),
        "timestamp": datetime.now(),
        "board_type": payload.get("board_type", BOARD_TYPE),
        "verdict": verdict,
        "fail_reason": fail_reason,
        "ocr_confidence": payload.get("ocr_confidence", 0.0),
        "defect_confidence": payload.get("defect_confidence", 0.0),
        "detected_components": detected,
        "image_url": payload.get("image_url", ""),
        "image_base64": payload.get("image_base64", ""),
        "routing": get_routing_info(verdict, fail_reason),
        "live": True,  # marks this row as real, not mock — used for the LIVE badge
        "manual": False,  # came from the conveyor/camera pipeline, not the manual tool
    }


def drain_mqtt_inbox():
    """
    Pulls everything the background thread has received since the last
    rerun and prepends new inspection records to history_df. Called once
    at the top of the script, before any page renders.
    """
    if not MQTT_AVAILABLE:
        return
    inbox = get_mqtt_inbox()
    new_rows = []
    while not inbox.empty():
        topic, payload = inbox.get()
        if topic == TOPIC_RESULT:
            new_rows.append(record_from_mqtt_payload(payload))
        elif topic == TOPIC_STATUS:
            # ESP32 confirming actual conveyor state — keep the sidebar
            # indicator honest instead of trusting only the button click.
            state = payload.get("state") if isinstance(payload, dict) else str(payload)
            if state in ("running", "stopped"):
                st.session_state.conveyor_running = (state == "running")
        elif topic == TOPIC_CAMERA_LIVE:
            # Just keep the most recent frame — no need to queue these up,
            # only the latest preview matters for the "is it detecting" view.
            st.session_state.live_camera_frame = payload.get("image_base64", "")
            st.session_state.live_camera_detections = payload.get("detections", [])
            st.session_state.live_camera_ts = payload.get("timestamp", "")

    if new_rows:
        add_history_rows(new_rows)


def publish_conveyor_cmd(command: str):
    """Publishes stop/resume to the ESP32. Falls back to local-only if MQTT isn't set up yet."""
    client = start_mqtt_client()
    if client is not None:
        client.publish(TOPIC_CMD, command)
    st.session_state.conveyor_running = (command == "resume")


# ----------------------------------------------------------------------
# OCR — this part is REAL, not mock
# ----------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def get_ocr_reader():
    return easyocr.Reader(["en"], gpu=False)


def read_serial_number(pil_image: Image.Image, enhance: bool = True, prefix: str = "SN"):
    img = np.array(pil_image.convert("RGB"))

    h_orig, w_orig = img.shape[:2]
    longest_side = max(h_orig, w_orig)
    if longest_side < 800:
        scale = 800 / longest_side
        new_size = (int(w_orig * scale), int(h_orig * scale))
        img = np.array(pil_image.convert("RGB").resize(new_size, Image.LANCZOS))

    if enhance:
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        gray = cv2.equalizeHist(gray)
        proc = cv2.cvtColor(gray, cv2.COLOR_GRAY2RGB)
    else:
        proc = img

    reader = get_ocr_reader()
    results = reader.readtext(proc, rotation_info=[90, 180, 270], mag_ratio=2.5)

    all_texts = [r[1] for r in results]

    if not results:
        return "", 0.0, all_texts

    def box_top_left(r):
        bbox = r[0]
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        return (round(min(ys), -1), min(xs))

    ordered = sorted(results, key=box_top_left)
    full_text = " ".join(r[1] for r in ordered)

    if prefix.strip():
        pattern = re.compile(rf"{re.escape(prefix)}\s*[-:]?\s*\w+", re.IGNORECASE)
        match = pattern.search(full_text)
        if match:
            matched_text = match.group().strip()
            contributing = [r[2] for r in results if r[1].lower() in matched_text.lower() or matched_text.lower() in r[1].lower()]
            confidence = sum(contributing) / len(contributing) if contributing else max(r[2] for r in results)
            return matched_text, confidence, all_texts
        return "", 0.0, all_texts

    best = max(results, key=lambda r: r[2])
    return best[1], float(best[2]), all_texts


# ----------------------------------------------------------------------
# MANUAL CAPTURE / UPLOAD — runs component detection + OCR on a single
# photo (webcam capture or uploaded file) so a full inspection record
# can still be produced, verdicted, and pushed into history_df even when
# the conveyor + bridge.py + camera_inference.py aren't running. Same
# Roboflow hosted model as camera_inference.py, called directly here.
# ----------------------------------------------------------------------
_manual_class_colors = {}


def _manual_class_color(class_name: str):
    if class_name not in _manual_class_colors:
        h = hash(class_name)
        _manual_class_colors[class_name] = ((h & 0xFF), (h >> 8) & 0xFF, (h >> 16) & 0xFF)
    return _manual_class_colors[class_name]


def run_manual_detection(pil_image: Image.Image):
    """
    Sends one image to the same Roboflow hosted model camera_inference.py
    uses, and returns (annotated_rgb_image_np, predictions). Returns
    (None, []) on any failure — network hiccup, bad key, etc. — so the
    caller can show a clear message instead of crashing the page.
    """
    if not REQUESTS_AVAILABLE:
        return None, []

    img = cv2.cvtColor(np.array(pil_image.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = img.shape[:2]
    scale = min(1.0, INFER_MAX_DIM / max(h, w))
    small = cv2.resize(img, (int(w * scale), int(h * scale))) if scale < 1.0 else img

    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return None, []

    try:
        response = requests.post(
            ROBOFLOW_API_URL,
            params={"api_key": ROBOFLOW_API_KEY, "confidence": int(CONFIDENCE_THRESHOLD * 100)},
            data=base64.b64encode(buf).decode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.session_state["_manual_detect_error"] = str(e)
        return None, []

    predictions = response.json().get("predictions", [])
    if scale < 1.0:
        inv = 1.0 / scale
        for p in predictions:
            p["x"] *= inv
            p["y"] *= inv
            p["width"] *= inv
            p["height"] *= inv

    annotated = img.copy()
    for pred in predictions:
        x1 = int(pred["x"] - pred["width"] / 2)
        y1 = int(pred["y"] - pred["height"] / 2)
        x2 = int(pred["x"] + pred["width"] / 2)
        y2 = int(pred["y"] + pred["height"] / 2)
        color = _manual_class_color(pred["class"])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{pred['class']} {pred['confidence']:.2f}"
        cv2.putText(annotated, label, (x1 + 2, max(y1 - 6, 12)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB), predictions


def build_manual_record(annotated_rgb, predictions, serial_number: str, ocr_confidence: float, board_id: str = "") -> dict:
    """
    Turns one manual capture into the same row shape record_from_mqtt_payload
    produces, so it flows through KPIs/charts/History identically. Verdict
    logic: FAIL if the serial couldn't be read, else FAIL for the first
    missing expected component, else PASS.
    """
    class_names = [p["class"] for p in predictions]
    detected = {name: class_names.count(name) for name in set(class_names)}
    missing = missing_components_list(detected)

    if not serial_number:
        verdict, fail_reason = "FAIL", "serial_unreadable"
    elif missing:
        verdict, fail_reason = "FAIL", f"missing_{missing[0]}"
    else:
        verdict, fail_reason = "PASS", "-"

    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(annotated_rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70]) \
        if annotated_rgb is not None else (False, None)
    image_b64 = base64.b64encode(buf).decode("utf-8") if ok else ""

    return {
        "board_id": board_id or f"BRD-MANUAL-{datetime.now().strftime('%H%M%S')}",
        "serial_number": serial_number or "UNREADABLE",
        "timestamp": datetime.now(),
        "board_type": BOARD_TYPE,
        "verdict": verdict,
        "fail_reason": fail_reason,
        "ocr_confidence": ocr_confidence,
        "defect_confidence": max([p["confidence"] for p in predictions], default=0.0),
        "detected_components": detected,
        "image_url": "",
        "image_base64": image_b64,
        "routing": get_routing_info(verdict, fail_reason),
        "live": False,
        "manual": True,  # came from the manual capture/upload tool, not the live pipeline
    }


def add_history_rows(records: list):
    """Prepends one or more records to history_df in one go."""
    new_df = pd.DataFrame(records)
    existing = st.session_state.history_df
    st.session_state.history_df = new_df if existing.empty else pd.concat(
        [new_df, existing], ignore_index=True
    )


def add_history_row(record: dict):
    """Prepends a single record to history_df."""
    add_history_rows([record])


# ----------------------------------------------------------------------
# HISTORY TABLE — starts empty; only real MQTT/manual inspection results
# get added from here on. No mock/seed rows.
# ----------------------------------------------------------------------
HISTORY_COLUMNS = [
    "board_id", "serial_number", "timestamp", "board_type", "verdict",
    "fail_reason", "ocr_confidence", "defect_confidence",
    "detected_components", "image_url", "image_base64", "routing", "live",
    "manual",
]


def empty_history_df():
    df = pd.DataFrame(columns=HISTORY_COLUMNS)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def render_board_image(row, **st_image_kwargs):
    """Shows the real captured image (base64, from a live MQTT record) when
    present, otherwise falls back to a URL, otherwise a neutral placeholder.
    Keeps History/Dashboard from silently displaying a fake stock photo
    next to a real inspection result."""
    b64 = row.get("image_base64", "") if hasattr(row, "get") else ""
    if b64:
        st.image(base64.b64decode(b64), **st_image_kwargs)
    elif row.get("image_url", ""):
        st.image(row["image_url"], **st_image_kwargs)
    else:
        st.image("https://placehold.co/320x220?text=No+Image", **st_image_kwargs)


def missing_components_list(detected: dict) -> list:
    return [c for c, expected in EXPECTED_COMPONENTS.items()
            if detected.get(c, 0) < expected]


def init_session_state():
    """Sets every session_state default exactly once, before any page reads it."""
    defaults = {
        "conveyor_running": True,
        "history_df": None,  # filled in below since it needs a function call
        "ocr_result": None,
        "page": "Dashboard",
        "session_start": datetime.now(),
        "live_camera_frame": "",
        "live_camera_detections": [],
        "live_camera_ts": "",
        "manual_last_result": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if st.session_state.history_df is None:
        st.session_state.history_df = empty_history_df()
