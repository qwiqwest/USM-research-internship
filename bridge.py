"""
Serial <-> MQTT bridge for the conveyor Arduino
--------------------------------------------------------------------------
Sits between the Arduino Uno (conveyor + IR sensor) and everything else.
This is the "bridge script" camera_inference.py's docstring and
dashboard.py's Settings page both refer to — it did not exist yet as a
file, so without it, nothing ever publishes to
semiconductor/conveyor/trigger and the triggered-inspection half of
camera_inference.py never fires.

What it does:
  1. Reads the Arduino's Serial.println() output line by line.
  2. When it sees the "object detected / paused" line, publishes to
     semiconductor/conveyor/trigger  -> camera_inference.py listens here.
  3. When it sees a button-toggle ON/OFF line, publishes a small status
     JSON to semiconductor/conveyor/status  -> dashboard.py can show this.

What it does NOT do yet:
  The current Arduino sketch only reacts to the physical button and the
  IR sensor — it does not read commands back over Serial. So the
  dashboard's Stop/Resume buttons (which publish to
  semiconductor/conveyor/cmd) are received here and logged, but nothing
  is sent to the Arduino yet. If you want Stop/Resume to actually control
  the belt, the sketch needs a small addition to read one character over
  Serial and toggle conveyorState — say if you want that added.

Setup:
    pip install pyserial paho-mqtt

Find your port:
    Windows : Device Manager -> Ports (COM&) -> e.g. "COM5"
    Mac     : ls /dev/tty.usbmodem*     (or /dev/tty.usbserial*)
    Linux   : ls /dev/ttyUSB* /dev/ttyACM*

Run with:
    python bridge.py
"""

import json
import time
from datetime import datetime

import serial
import paho.mqtt.client as mqtt

# ----------------------------------------------------------------------
# CONFIG — edit these two for your setup
# ----------------------------------------------------------------------
SERIAL_PORT = "COM3"        # <-- change to your Arduino's port
BAUD_RATE = 9600            # must match Serial.begin() in the .ino file

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

TOPIC_TRIGGER = "semiconductor/conveyor/trigger"
TOPIC_STATUS = "semiconductor/conveyor/status"
TOPIC_CMD = "semiconductor/conveyor/cmd"

# ----------------------------------------------------------------------
# MQTT
# ----------------------------------------------------------------------
def on_connect(client, userdata, flags, rc, properties=None):
    print(f"MQTT connected (rc={rc}), subscribing to {TOPIC_CMD}")
    client.subscribe(TOPIC_CMD)


def on_message(client, userdata, msg):
    # Dashboard Stop/Resume buttons land here. Logged for now — see the
    # docstring above about the sketch not yet accepting Serial commands.
    print(f"[cmd received] {msg.topic}: {msg.payload.decode(errors='replace')} "
          f"(not yet forwarded to the Arduino)")


mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message
mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
mqtt_client.loop_start()

# ----------------------------------------------------------------------
# SERIAL
# ----------------------------------------------------------------------
print(f"Opening serial port {SERIAL_PORT} @ {BAUD_RATE}...")
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
time.sleep(2)  # let the Arduino finish its reset after the port opens

print("Bridge running. Watching for conveyor events... Ctrl+C to stop.")
try:
    while True:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode(errors="replace").strip()
        if not line:
            continue

        print(f"[arduino] {line}")

        if "Objek terdeteksi" in line or "PAUSED" in line:
            mqtt_client.publish(TOPIC_TRIGGER, json.dumps({
                "reason": "ir_object_detected",
                "timestamp": datetime.now().isoformat(),
            }))
            print(" -> published trigger")

        elif "Conveyor di-set:" in line:
            state = "ON" if "ON" in line else "OFF"
            mqtt_client.publish(TOPIC_STATUS, json.dumps({
                "conveyor_state": state,
                "timestamp": datetime.now().isoformat(),
            }))
            print(f" -> published status: {state}")

except KeyboardInterrupt:
    print("\nShutting down bridge...")
finally:
    mqtt_client.loop_stop()
    ser.close()