#!/usr/bin/env python3
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict

from flask import Flask, jsonify, render_template, request, send_from_directory

try:
    from pymodbus.client import ModbusTcpClient
except ImportError as exc:
    raise SystemExit("pymodbus not installed. Install dependencies from requirements.txt") from exc


app = Flask(__name__)


@dataclass(frozen=True)
class SlotConfig:
    slot_id: str
    name: str
    start_coil: int
    stop_coil: int
    running_status_coil: int
    video_file: str


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


MODBUS_SERVER_IP = os.environ.get("MODBUS_SERVER_IP", "192.168.1.100")
MODBUS_SERVER_PORT = _env_int("MODBUS_SERVER_PORT", 504)
MODBUS_TIMEOUT_SECONDS = _env_float("MODBUS_TIMEOUT_SECONDS", 1.5)
MODBUS_UNIT_ID = _env_int("MODBUS_UNIT_ID", 1)
COIL_PULSE_SECONDS = _env_float("COIL_PULSE_SECONDS", 0.25)
STATUS_POLL_COIL_START = _env_int("STATUS_POLL_COIL_START", 0)
STATUS_POLL_COIL_COUNT = _env_int("STATUS_POLL_COIL_COUNT", 64)

SLOTS: Dict[str, SlotConfig] = {
    "slot1": SlotConfig(
        slot_id="slot1",
        name="Helmet Wash Slot 1",
        start_coil=_env_int("SLOT1_START_COIL", 10),
        stop_coil=_env_int("SLOT1_STOP_COIL", 11),
        running_status_coil=_env_int("SLOT1_RUNNING_COIL", 20),
        video_file=os.environ.get("SLOT1_VIDEO", "Guide_steps.mp4"),
    ),
    "slot2": SlotConfig(
        slot_id="slot2",
        name="Helmet Wash Slot 2",
        start_coil=_env_int("SLOT2_START_COIL", 12),
        stop_coil=_env_int("SLOT2_STOP_COIL", 13),
        running_status_coil=_env_int("SLOT2_RUNNING_COIL", 21),
        video_file=os.environ.get("SLOT2_VIDEO", "Process_step_3.mp4"),
    ),
}


modbus_client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT, timeout=MODBUS_TIMEOUT_SECONDS)
modbus_lock = threading.Lock()


def _connect_if_needed() -> None:
    if getattr(modbus_client, "connected", False):
        return
    ok = modbus_client.connect()
    if not ok:
        raise RuntimeError(
            f"Unable to connect to PLC at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}"
        )


def _write_pulse(coil_address: int) -> None:
    with modbus_lock:
        _connect_if_needed()
        result = modbus_client.write_coil(coil_address, True, slave=MODBUS_UNIT_ID)
        if hasattr(result, "isError") and result.isError():
            raise RuntimeError(f"PLC write failed at coil {coil_address}: {result}")
        time.sleep(COIL_PULSE_SECONDS)
        result = modbus_client.write_coil(coil_address, False, slave=MODBUS_UNIT_ID)
        if hasattr(result, "isError") and result.isError():
            raise RuntimeError(f"PLC pulse reset failed at coil {coil_address}: {result}")


def _read_running_status() -> Dict[str, bool]:
    out = {slot_id: False for slot_id in SLOTS}
    with modbus_lock:
        _connect_if_needed()
        result = modbus_client.read_coils(
            STATUS_POLL_COIL_START,
            count=STATUS_POLL_COIL_COUNT,
            slave=MODBUS_UNIT_ID,
        )
        if hasattr(result, "isError") and result.isError():
            raise RuntimeError(f"PLC read failed: {result}")

        bits = list(getattr(result, "bits", []) or [])
        for slot_id, slot in SLOTS.items():
            idx = slot.running_status_coil - STATUS_POLL_COIL_START
            out[slot_id] = bool(bits[idx]) if 0 <= idx < len(bits) else False

    return out


@app.route("/")
def index():
    return render_template("dual_control.html", slots=SLOTS)


@app.route("/videos/<path:filename>")
def videos(filename: str):
    # Serves videos already present in this project folder.
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), filename)


@app.post("/api/slot/<slot_id>/<action>")
def control_slot(slot_id: str, action: str):
    slot = SLOTS.get(slot_id)
    if not slot:
        return jsonify({"ok": False, "error": f"Unknown slot: {slot_id}"}), 404

    if action not in ("start", "stop"):
        return jsonify({"ok": False, "error": f"Unknown action: {action}"}), 400

    try:
        target_coil = slot.start_coil if action == "start" else slot.stop_coil
        _write_pulse(target_coil)
        return jsonify({
            "ok": True,
            "slot": slot_id,
            "action": action,
            "coil": target_coil,
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/status")
def get_status():
    try:
        running = _read_running_status()
        return jsonify(
            {
                "ok": True,
                "modbus": {
                    "server": MODBUS_SERVER_IP,
                    "port": MODBUS_SERVER_PORT,
                    "connected": bool(modbus_client.connected),
                },
                "slots": {
                    slot_id: {
                        "name": slot.name,
                        "running": running.get(slot_id, False),
                        "start_coil": slot.start_coil,
                        "stop_coil": slot.stop_coil,
                        "running_status_coil": slot.running_status_coil,
                        "video": slot.video_file,
                    }
                    for slot_id, slot in SLOTS.items()
                },
            }
        )
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "flask_dual_control"})


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = _env_int("FLASK_PORT", 8080)
    app.run(host=host, port=port, debug=False)
