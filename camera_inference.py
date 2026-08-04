"""
Camera + trained YOLOv11 (via Roboflow Hosted API) script
--------------------------------------------------------------------------
Two things run at once:

1. LIVE PREVIEW (continuous, low frame rate)
   Grabs a frame from the USB camera every LIVE_INTERVAL_SEC, sends it to
   Roboflow's hosted inference API, and publishes the annotated frame +
   detected class names to MQTT so the dashboard can show "camera is
   detecting" in near-real-time, independent of the conveyor.

2. TRIGGERED INSPECTION (event-driven)
   Subscribes to semiconductor/conveyor/trigger (published by the bridge
   script the moment the Uno's IR sensor fires and pauses the belt).
   When a trigger arrives, grabs a fresh frame, runs inference again, and
   publishes a full inspection record to semiconductor/inspection/result
   — the same topic the dashboard's History/KPIs already read from.

WHY THIS VERSION EXISTS: Roboflow's local `inference` package requires
Python <3.13. If you're on Python 3.13 and don't want to install a second
Python version just for this, this version calls Roboflow's hosted REST
API directly with plain `requests` instead — no version-locked package
needed. The tradeoff: every inference call needs an internet connection
and sends your frame to Roboflow's servers, adding network latency. Fine
for testing; for the final deployed system, switch back to the local
`inference` package (see camera_inference_local.py) once you're on a
Python 3.9-3.12 environment, so triggered captures don't depend on network
round-trip time during the belt's timed pause window.

Setup:
    pip install opencv-python paho-mqtt requests

You'll need:
    - Your Roboflow PRIVATE API key (Roboflow account -> Settings -> API Keys)
    - Your model ID, shaped like "project-slug/version", e.g. "board-oqvfa/1"
      — check the Model URL field on your model's page in Roboflow.

Run with:
    python camera_inference.py
"""

import base64
import json
import threading
import time
from datetime import datetime

import cv2
import requests
import paho.mqtt.client as mqtt

# ----------------------------------------------------------------------
# CONFIG
# ----------------------------------------------------------------------
CAMERA_INDEX = 0           # 0 is usually the default/first USB camera
MQTT_BROKER = "localhost"   # same broker dashboard.py and the bridge use
MQTT_PORT = 1883

ROBOFLOW_API_KEY = "Mv5CfziDdtMzclAQjaep"     # Roboflow account -> Settings -> API Keys
MODEL_ID = "nurs-workspace-yquat/board-oqvfa-1-yolo11n-t2"            # check your model's Model URL field for the exact string
CONFIDENCE_THRESHOLD = 0.5            # ignore detections below this confidence (0-1 scale)
ROBOFLOW_API_URL = f"https://detect.roboflow.com/{MODEL_ID}"

TOPIC_TRIGGER = "semiconductor/conveyor/trigger"
TOPIC_RESULT = "semiconductor/inspection/result"
TOPIC_CAMERA_LIVE = "semiconductor/camera/live"

LIVE_INTERVAL_SEC = 0.2     # how often the PREVIEW publishes (camera capture only, fast/local)
JPEG_QUALITY = 60           # lower = smaller MQTT payload, still fine for a preview

INFER_MAX_DIM = 640

# ----------------------------------------------------------------------
# CAMERA
# ----------------------------------------------------------------------
print(f"Opening camera index {CAMERA_INDEX}...")
cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)  # DirectShow avoids MSMF grabFrame errors on Windows
if not cap.isOpened():
    raise RuntimeError(f"Could not open camera index {CAMERA_INDEX}. Try a different index.")

# Lock so the trigger callback (runs on the MQTT thread) and the main
# live-preview loop don't both grab from the camera at the exact same instant.
camera_lock = threading.Lock()

# Fixed colors per class so boxes are visually consistent across frames,
# rather than random colors that flicker between detections.
_class_colors = {}


def get_class_color(class_name: str):
    if class_name not in _class_colors:
        # Deterministic pseudo-random color from the class name's hash,
        # so the same class always gets the same box color.
        h = hash(class_name)
        _class_colors[class_name] = ((h & 0xFF), (h >> 8) & 0xFF, (h >> 16) & 0xFF)
    return _class_colors[class_name]


def annotate_frame(frame, predictions):
    """
    Draws bounding boxes + labels on a copy of the frame. The hosted API
    returns predictions as plain dicts with center x/y + width/height in
    pixels — same shape whether you call it directly or through the SDK.
    """
    annotated = frame.copy()
    for pred in predictions:
        x1 = int(pred["x"] - pred["width"] / 2)
        y1 = int(pred["y"] - pred["height"] / 2)
        x2 = int(pred["x"] + pred["width"] / 2)
        y2 = int(pred["y"] + pred["height"] / 2)
        color = get_class_color(pred["class"])

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{pred['class']} {pred['confidence']:.2f}"
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(annotated, (x1, y1 - label_h - 8), (x1 + label_w + 4, y1), color, -1)
        cv2.putText(annotated, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return annotated


def run_hosted_inference(frame):
    """
    Sends one frame to Roboflow's hosted API and returns the filtered
    predictions list, scaled back to the ORIGINAL frame's coordinates.
    Each prediction is a plain dict with keys: x, y, width, height,
    confidence, class.

    The frame is downscaled first (INFER_MAX_DIM) so the upload/round-trip
    is faster — this is the single biggest lever on perceived lag, since
    this call is the slow part of the whole pipeline.
    """
    h, w = frame.shape[:2]
    scale = min(1.0, INFER_MAX_DIM / max(h, w))
    small = cv2.resize(frame, (int(w * scale), int(h * scale))) if scale < 1.0 else frame

    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 70])
    if not ok:
        return []
    img_b64 = base64.b64encode(buf).decode("utf-8")

    try:
        response = requests.post(
            ROBOFLOW_API_URL,
            params={"api_key": ROBOFLOW_API_KEY, "confidence": int(CONFIDENCE_THRESHOLD * 100)},
            data=img_b64,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        # Network hiccup or bad API key/model ID — don't crash the whole
        # script over one failed call, just skip this frame's detections.
        print(f"Roboflow API call failed: {e}")
        return []

    predictions = response.json().get("predictions", [])
    if scale < 1.0:
        # Predictions came back in the resized image's coordinate space —
        # scale them back up so boxes line up on the original frame.
        inv = 1.0 / scale
        for p in predictions:
            p["x"] *= inv
            p["y"] *= inv
            p["width"] *= inv
            p["height"] *= inv
    return predictions


def capture_and_infer():
    """
    Used ONLY for triggered inspections (on-demand, one-shot — a brief
    block here is fine since it's not the continuous preview loop).
    Grabs one frame, runs the trained model via the hosted API, returns
    (annotated_frame, list_of_class_names).
    """
    with camera_lock:
        ok, frame = cap.read()
    if not ok:
        return None, []

    predictions = run_hosted_inference(frame)
    annotated = annotate_frame(frame, predictions)
    class_names = [p["class"] for p in predictions]
    return annotated, class_names


# ----------------------------------------------------------------------
# BACKGROUND INFERENCE (for the live preview only)
# ----------------------------------------------------------------------
# The preview loop below just grabs+publishes frames as fast as it can —
# it never waits on Roboflow. This thread separately keeps calling the
# hosted API against whatever the latest captured frame is, and stores
# the most recent predictions. The preview loop draws whatever's in
# `latest_predictions` at the moment it publishes, so boxes may lag the
# live feed by up to one inference round-trip (usually a few hundred ms
# to ~1s) instead of the whole feed lagging by that amount.
_latest_frame = None
_latest_frame_lock = threading.Lock()
_latest_predictions = []
_latest_predictions_lock = threading.Lock()


def inference_worker():
    while True:
        with _latest_frame_lock:
            frame = None if _latest_frame is None else _latest_frame.copy()
        if frame is not None:
            preds = run_hosted_inference(frame)
            with _latest_predictions_lock:
                global _latest_predictions
                _latest_predictions = preds
        # No sleep needed beyond what the API call itself takes — as soon
        # as one call finishes it immediately starts the next, so this
        # thread runs at whatever cadence the network allows.


def frame_to_base64_jpg(frame) -> str:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    if not ok:
        return ""
    return base64.b64encode(buf).decode("utf-8")


# ----------------------------------------------------------------------
# MQTT
# ----------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"MQTT connected (rc={rc}), subscribing to {TOPIC_TRIGGER}")
    client.subscribe(TOPIC_TRIGGER)


def on_message(client, userdata, msg):
    if msg.topic != TOPIC_TRIGGER:
        return
    print("Trigger received from conveyor — running inspection capture.")
    annotated, class_names = capture_and_infer()
    if annotated is None:
        print("Camera read failed, skipping this trigger.")
        return

    payload = {
        "board_id": f"BRD-LIVE-{datetime.now().strftime('%H%M%S')}",
        "serial_number": "UNREADABLE",  # OCR is handled separately in the dashboard's Live Inspection page
        "verdict": "PASS" if class_names else "FAIL",
        "fail_reason": "-" if class_names else "serial_unreadable",
        "detected_components": {name: class_names.count(name) for name in set(class_names)},
        "ocr_confidence": 0.0,
        "defect_confidence": 0.9 if class_names else 0.0,
        "image_base64": frame_to_base64_jpg(annotated),
    }
    client.publish(TOPIC_RESULT, json.dumps(payload))
    print(f"Published inspection result: {class_names or 'no detections'}")


mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
mqtt_client.loop_start()


# ----------------------------------------------------------------------
# LIVE PREVIEW LOOP (runs continuously regardless of conveyor triggers)
# ----------------------------------------------------------------------
print("Starting background inference thread + live preview loop. Press Ctrl+C to stop.")
threading.Thread(target=inference_worker, daemon=True).start()

try:
    while True:
        with camera_lock:
            ok, frame = cap.read()
        if ok:
            with _latest_frame_lock:
                _latest_frame = frame

            with _latest_predictions_lock:
                preds = _latest_predictions

            annotated = annotate_frame(frame, preds)
            class_names = [p["class"] for p in preds]
            live_payload = {
                "image_base64": frame_to_base64_jpg(annotated),
                "detections": class_names,
                "timestamp": datetime.now().isoformat(),
            }
            mqtt_client.publish(TOPIC_CAMERA_LIVE, json.dumps(live_payload))
        time.sleep(LIVE_INTERVAL_SEC)
except KeyboardInterrupt:
    print("\nShutting down camera script...")
finally:
    mqtt_client.loop_stop()
    cap.release()