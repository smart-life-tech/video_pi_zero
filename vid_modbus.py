#!/usr/bin/env python3
import os
import time
import socket
import subprocess
import shutil
import sys
import logging

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("ERROR: pymodbus not installed. Install with: pip install pymodbus")
    sys.exit(1)

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("debug_modbus.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("vid_modbus")

# ===============================
# X11 ENV (MATCH vid_test)
# ===============================
os.environ["DISPLAY"] = ":0"
os.environ["XDG_SESSION_TYPE"] = "x11"
os.environ["QT_QPA_PLATFORM"] = "xcb"

home = os.path.expanduser("~")
xauth = os.path.join(home, ".Xauthority")
if os.path.exists(xauth):
    os.environ["XAUTHORITY"] = xauth

# ===============================
# CONFIG
# ===============================
VIDEOS = [
    "Guide_steps.mp4",
    "Process_step_1.mp4",
    "Warning.mp4",
    "Process_step_2.mp4",
    "Process_step_3.mp4",
]

VIDEO_INDEX = {name: idx + 1 for idx, name in enumerate(VIDEOS)}  # VLC playlist goto is 1-based

# coil -> action
MODBUS_COILS = {
    "Process_step_1": 0,
    "Guide_steps": 1,
    "Warning": 2,
    "Process_step_2": 3,
    "Process_step_3": 4,
}

VIDEO_FILES = {
    "Process_step_1": "Process_step_1.mp4",
    "Guide_steps": "Guide_steps.mp4",
    "Warning": "Warning.mp4",
    "Process_step_2": "Process_step_2.mp4",
    "Process_step_3": "Process_step_3.mp4",
}

MODBUS_SERVER_IP = os.environ.get("MODBUS_SERVER_IP", "192.168.1.100")
MODBUS_SERVER_PORT = int(os.environ.get("MODBUS_SERVER_PORT", "504"))
MODBUS_UNIT_ID = int(os.environ.get("MODBUS_UNIT_ID", "1"))

MODBUS_POLL_INTERVAL_SECONDS = float(os.environ.get("MODBUS_POLL_INTERVAL", "0.1"))
MODBUS_RECONNECT_DELAY_SECONDS = float(os.environ.get("MODBUS_RECONNECT_DELAY", "1.0"))
TRIGGER_COOLDOWN_SECONDS = float(os.environ.get("TRIGGER_COOLDOWN_SECONDS", "0.8"))

RC_HOST = "127.0.0.1"
RC_PORT = int(os.environ.get("VLC_RC_PORT", "4213"))

modbus_client = None
last_trigger_time = {key: 0.0 for key in MODBUS_COILS}


# ===============================
# HELPERS
# ===============================
def resolve_video_path(filename: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        filename,
        os.path.join(script_dir, filename),
        os.path.join(os.getcwd(), "Videos", filename),
        os.path.join("/home/helmwash/video_pi_zero", filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return filename


def rc(cmd: str):
    try:
        s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.6)
        s.sendall((cmd + "\n").encode("utf-8"))
        s.close()
    except Exception:
        pass


def wait_for_rc(timeout=8) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.3)
            s.close()
            return True
        except Exception:
            time.sleep(0.1)
    return False


def start_vlc(dummy_video: str):
    if not shutil.which("cvlc"):
        log.error("cvlc not installed")
        sys.exit(1)

    cmd = [
        "cvlc",
        "--intf", "dummy",
        "--extraintf", "rc",
        "--rc-host", f"{RC_HOST}:{RC_PORT}",
        "--vout", "x11",
        "--avcodec-hw=none",
        "--video-x", "0",
        "--video-y", "0",
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-osd",
        "--no-audio",
        dummy_video,
    ]

    log.info("Launching VLC RC controller")
    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
        start_new_session=True,
    )

    if not wait_for_rc():
        log.error("VLC RC interface did not respond")
        sys.exit(1)


def build_playlist(video_paths):
    # EXACT same method pattern as vid_test
    rc("stop")
    rc("clear")
    rc("repeat off")
    rc("loop on")
    rc("random off")

    rc(f"add {video_paths[0]}")
    time.sleep(0.1)
    for v in video_paths[1:]:
        rc(f"enqueue {v}")
        time.sleep(0.05)

    rc("seek 0")
    rc("play")
    rc("fullscreen on")


def switch_to_video(video_file: str):
    idx = VIDEO_INDEX.get(video_file)
    if idx is None:
        return

    # Loop warning until another trigger arrives
    if video_file == "Warning.mp4":
        rc("repeat on")
    else:
        rc("repeat off")

    rc(f"goto {idx}")
    rc("seek 0")
    rc("play")
    rc("fullscreen on")

    log.info(f"Switched to: {video_file}")


def can_trigger(action_name: str) -> bool:
    now = time.time()
    if now - last_trigger_time[action_name] < TRIGGER_COOLDOWN_SECONDS:
        return False
    last_trigger_time[action_name] = now
    return True


def connect_modbus() -> bool:
    global modbus_client
    try:
        if modbus_client:
            try:
                modbus_client.close()
            except Exception:
                pass

        modbus_client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT, timeout=2)
        ok = modbus_client.connect()
        if ok:
            log.info(f"Connected Modbus {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
        else:
            log.error("Failed to connect Modbus")
        return ok
    except Exception as e:
        log.error(f"Modbus connect error: {e}")
        return False


def read_coils():
    if not modbus_client:
        return None
    try:
        try:
            result = modbus_client.read_coils(0, count=5, device_id=MODBUS_UNIT_ID)
        except TypeError:
            try:
                result = modbus_client.read_coils(0, count=5, slave=MODBUS_UNIT_ID)
            except TypeError:
                result = modbus_client.read_coils(0, count=5, unit=MODBUS_UNIT_ID)

        if result.isError():
            return None
        return result.bits[:5]
    except Exception:
        return None


# ===============================
# MAIN
# ===============================
def main():
    log.info("Starting merged vid_modbus (vid_test switch method + Modbus rising-edge trigger)")

    video_paths = []
    for v in VIDEOS:
        p = os.path.abspath(resolve_video_path(v))
        if os.path.exists(p):
            video_paths.append(p)
        else:
            log.warning(f"Missing video: {p}")

    if not video_paths:
        log.error("No valid videos found")
        return

    # Startup VLC + playlist with same method as vid_test
    start_vlc(video_paths[0])
    build_playlist(video_paths)

    # Start on guide
    switch_to_video("Guide_steps.mp4")

    if not connect_modbus():
        print("Could not connect to Modbus PLC")
        return

    print("Monitoring coils 0-4 (rising edge only). Ctrl+C to exit.")
    last_states = [False] * 5

    try:
        while True:
            states = read_coils()
            if states is None:
                log.warning("Modbus read failed, reconnecting...")
                time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
                connect_modbus()
                time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
                continue

            for idx, (action_name, coil_addr) in enumerate(MODBUS_COILS.items()):
                current = bool(states[idx])
                previous = bool(last_states[idx])

                # Rising edge only
                if current and not previous:
                    if can_trigger(action_name):
                        video_file = VIDEO_FILES[action_name]
                        log.info(f"Rising edge coil {coil_addr}: {action_name} -> {video_file}")
                        switch_to_video(video_file)

                last_states[idx] = current

            time.sleep(MODBUS_POLL_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        log.info("Interrupted by user")
    finally:
        try:
            if modbus_client:
                modbus_client.close()
        except Exception:
            pass
        rc("stop")
        log.info("Shutdown complete")


if __name__ == "__main__":
    main()
