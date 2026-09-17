#!/usr/bin/env python3
"""Read a configured Modbus liquid sensor and post signed readings to the API."""

import hashlib
import hmac
import json
import logging
import os
import random
import time
from datetime import datetime, timezone

import requests
from pymodbus.client import ModbusTcpClient

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("liquid-level-sender")

API_BASE = os.environ["HW_API_BASE"].rstrip("/")
DEVICE_ID = os.environ["HW_DEVICE_ID"]
KEY_ID = os.environ.get("HW_KEY_ID", "v1")
DEVICE_SECRET = os.environ["HW_DEVICE_SECRET"]
FIRMWARE = os.environ.get("FIRMWARE_VERSION", "unknown")
PATH = "/api/v1/ingest/status"
INTERVAL = int(os.environ.get("READING_INTERVAL_SECONDS", "300"))
JITTER = int(os.environ.get("READING_JITTER_SECONDS", "30"))
MAX_BACKOFF = 300

PLC_HOST = os.environ.get("MODBUS_SERVER_IP", "192.168.1.100")
PLC_PORT = int(os.environ.get("MODBUS_SERVER_PORT", "504"))
PLC_UNIT = int(os.environ.get("MODBUS_UNIT_ID", "1"))
LEVEL_REGISTER = os.environ.get("LIQUID_LEVEL_REGISTER")
LOW_COIL = os.environ.get("LIQUID_LOW_COIL")
RAW_MIN = float(os.environ.get("LIQUID_RAW_MIN", "0"))
RAW_MAX = float(os.environ.get("LIQUID_RAW_MAX", "4095"))


def sign(timestamp: int, raw_body: bytes) -> str:
    body_hash = hashlib.sha256(raw_body).hexdigest()
    canonical = "\n".join(["POST", PATH, str(timestamp), DEVICE_ID, body_hash])
    return hmac.new(DEVICE_SECRET.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def percent_from_raw(raw_value: int):
    if RAW_MAX <= RAW_MIN:
        raise ValueError("LIQUID_RAW_MAX must be greater than LIQUID_RAW_MIN")
    percent = (float(raw_value) - RAW_MIN) / (RAW_MAX - RAW_MIN) * 100
    return max(0, min(100, round(percent)))


def read_sensor():
    """Return (Pi state, percent) using the configured PLC addresses.

    LIQUID_LEVEL_REGISTER is optional. If omitted, percent is null as required for
    machines without a level sensor. LIQUID_LOW_COIL is required in that case.
    """
    if not LEVEL_REGISTER and not LOW_COIL:
        raise RuntimeError("Configure LIQUID_LEVEL_REGISTER or LIQUID_LOW_COIL")

    client = ModbusTcpClient(PLC_HOST, port=PLC_PORT, timeout=2)
    try:
        if not client.connect():
            raise ConnectionError(f"Cannot connect to PLC {PLC_HOST}:{PLC_PORT}")

        percent = None
        if LEVEL_REGISTER:
            result = client.read_holding_registers(int(LEVEL_REGISTER), count=1, slave=PLC_UNIT)
            if result.isError():
                raise RuntimeError(f"Level register read failed: {result}")
            percent = percent_from_raw(result.registers[0])

        if LOW_COIL:
            result = client.read_coils(int(LOW_COIL), count=1, slave=PLC_UNIT)
            if result.isError():
                raise RuntimeError(f"Low-level coil read failed: {result}")
            state = "low" if bool(result.bits[0]) else "ok"
        elif percent is not None:
            state = "low" if percent <= 10 else "ok"
        else:
            raise RuntimeError("A low-level coil is required when no level register is configured")

        return state, percent
    finally:
        client.close()


def post_reading(state: str, percent):
    payload = {
        "machineId": DEVICE_ID,
        "liquid": {"state": state, "percent": percent},
        "firmware": FIRMWARE,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    timestamp = int(time.time())
    response = requests.post(
        API_BASE + PATH,
        data=body,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-HW-Device-Id": DEVICE_ID,
            "X-HW-Timestamp": str(timestamp),
            "X-HW-Key-Id": KEY_ID,
            "X-HW-Signature": sign(timestamp, body),
        },
        timeout=10,
    )
    return response


def retry_delay(response, backoff):
    retry_after = response.headers.get("Retry-After", "") if response is not None else ""
    return int(retry_after) if retry_after.isdigit() else backoff


def run():
    backoff = 5
    while True:
        wait = INTERVAL + random.randint(-JITTER, JITTER)
        try:
            state, percent = read_sensor()
            response = post_reading(state, percent)
            if response.status_code == 202:
                log.info("Reading accepted: state=%s percent=%s", state, percent)
                backoff = 5
            elif response.status_code == 429 or response.status_code >= 500:
                wait = retry_delay(response, backoff)
                backoff = min(backoff * 2, MAX_BACKOFF)
                log.warning("Temporary API response %s; retrying in %ss", response.status_code, wait)
            else:
                log.error("Permanent API response %s: %s", response.status_code, response.text[:300])
                backoff = 5
        except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
            wait = backoff
            backoff = min(backoff * 2, MAX_BACKOFF)
            log.warning("Reading/send failed: %s; retrying in %ss", exc, wait)
        time.sleep(max(1, wait))


if __name__ == "__main__":
    run()
