#!/usr/bin/env python3
# export XDG_SESSION_TYPE=x11
# export QT_QPA_PLATFORM=xcb
# python vid_modbus.py

import os
import sys
import time
import socket
import shutil
import logging
import subprocess

# -------------------------------
# Environment / Logging
# -------------------------------
if sys.platform.startswith("linux"):
    os.environ.setdefault("DISPLAY", ":0")
    os.environ.setdefault("XDG_SESSION_TYPE", "x11")
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    xauth = os.path.join(os.path.expanduser("~"), ".Xauthority")
    if os.path.exists(xauth):
        os.environ.setdefault("XAUTHORITY", xauth)

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_modbus.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("vid_modbus")

# -------------------------------
# Modbus
# -------------------------------
try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("ERROR: pymodbus not installed. Install with: pip install pymodbus")
    sys.exit(1)

MODBUS_SERVER_IP = "192.168.1.100"
MODBUS_SERVER_PORT = int(os.environ.get("MODBUS_SERVER_PORT", "504"))
MODBUS_UNIT_ID = 1
MODBUS_POLL_INTERVAL_SECONDS = float(os.environ.get("MODBUS_POLL_INTERVAL", "0.1"))
MODBUS_RECONNECT_DELAY_SECONDS = float(os.environ.get("MODBUS_RECONNECT_DELAY", "1.0"))

# Rising-edge debounce (simple)
COOLDOWN_SECONDS = float(os.environ.get("TRIGGER_COOLDOWN_SECONDS", "0.8"))

# -------------------------------
# Video Mapping
# -------------------------------
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

PLAYLIST_ORDER = [
    "Guide_steps.mp4",
    "Process_step_1.mp4",
    "Warning.mp4",
    "Process_step_2.mp4",
    "Process_step_3.mp4",
]

last_trigger_time = {name: 0.0 for name in VIDEO_FILES}

# -------------------------------
# VLC RC
# -------------------------------
RC_HOST = "127.0.0.1"
RC_PORT = int(os.environ.get("VLC_RC_PORT", "4213"))
vlc_proc = None
playlist_id_by_file = {}


def resolve_video_path(filename: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        filename,
        os.path.join(script_dir, filename),
        os.path.join(os.getcwd(), "Videos", filename),
        os.path.join("/home/helmwash/video_pi_zero", filename),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return filename


def get_player_cmd():
    if shutil.which("cvlc"):
        return "cvlc"
    if shutil.which("vlc"):
        return "vlc"
    return None


def rc_send(command: str, timeout: float = 0.8) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((RC_HOST, RC_PORT))
        s.sendall((command + "\n").encode("utf-8", errors="ignore"))
        chunks = []
        while True:
            try:
                data = s.recv(4096)
                if not data:
                    break
                chunks.append(data)
                if len(data) < 4096:
                    break
            except socket.timeout:
                break
        return b"".join(chunks).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    finally:
        try:
            s.close()
        except Exception:
            pass


def wait_for_rc(timeout_seconds: float = 8.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if vlc_proc and vlc_proc.poll() is not None:
            return False
        try:
            s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.4)
            s.close()
            return True
        except Exception:
            time.sleep(0.1)
    return False


def start_vlc_controller(first_video_path: str) -> bool:
    global vlc_proc
    player = get_player_cmd()
    if not player:
        log.error("VLC not found. Install VLC/cvlc.")
        return False

    if vlc_proc and vlc_proc.poll() is None:
        return True

    cmd = [
        player,
        "--intf", "dummy",
        "--extraintf", "rc",
        "--rc-host", f"{RC_HOST}:{RC_PORT}",
        "--vout", "x11",
        "--avcodec-hw=none",
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-video-deco",
        "--no-qt-fs-controller",
        "--quiet",
        "--no-audio",
        first_video_path,
    ]

    log.info("Starting VLC RC controller")
    vlc_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=os.environ.copy(),
        start_new_session=True,
    )

    if not wait_for_rc():
        log.error("VLC RC interface did not respond")
        return False

    return True


def preload_playlist() -> bool:
    global playlist_id_by_file

    resolved = []
    for name in PLAYLIST_ORDER:
        p = resolve_video_path(name)
        if os.path.exists(p):
            resolved.append((name, p))
        else:
            log.warning(f"Missing video: {p}")

    if not resolved:
        log.error("No videos available for playlist")
        return False

    rc_send("stop")
    rc_send("clear")
    rc_send("repeat off")
    rc_send("loop on")
    rc_send("random off")

    first_name, first_path = resolved[0]
    rc_send(f"add {first_path}")
    time.sleep(0.1)

    for _name, path in resolved[1:]:
        rc_send(f"enqueue {path}")
        time.sleep(0.05)

    rc_send("seek 0")
    rc_send("play")
    rc_send("fullscreen on")

    # Build ID map for direct goto by filename when available.
    text = rc_send("playlist", timeout=1.2)
    id_map = {}
    for line in text.splitlines():
        low = line.lower()
        # line format usually contains "- <id> -"
        parts = line.split("-")
        if len(parts) < 2:
            continue
        maybe_id = parts[1].strip() if parts[0].strip() == "" else parts[0].strip()
        try:
            item_id = int(maybe_id)
        except Exception:
            continue
        for fname, _ in resolved:
            if fname.lower() in low and fname not in id_map:
                id_map[fname] = item_id

    playlist_id_by_file = id_map
    log.info(f"Playlist preloaded. IDs: {playlist_id_by_file}")
    log.info(f"Started: {first_name}")
    return True


def switch_video(video_file: str):
    path = resolve_video_path(video_file)
    if not os.path.exists(path):
        log.warning(f"Missing target video: {path}")
        return

    # Warning loops; others play once.
    if video_file == "Warning.mp4":
        rc_send("repeat on")
    else:
        rc_send("repeat off")

    if video_file in playlist_id_by_file:
        rc_send(f"goto {playlist_id_by_file[video_file]}")
        rc_send("seek 0")
        rc_send("play")
        rc_send("fullscreen on")
    else:
        # Fallback if playlist ID was not detected
        rc_send("stop")
        rc_send("clear")
        rc_send(f"add {path}")
        rc_send("seek 0")
        rc_send("play")
        rc_send("fullscreen on")

    log.info(f"Switched to: {video_file}")


# -------------------------------
# Modbus Helpers
# -------------------------------
modbus_client = None


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
            log.info(f"Connected to Modbus: {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
            return True
        log.error("Modbus connect failed")
        return False
    except Exception as e:
        log.error(f"Modbus connect error: {e}")
        return False


def read_coils() -> list | None:
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


def can_trigger(action_name: str) -> bool:
    now = time.time()
    if now - last_trigger_time[action_name] < COOLDOWN_SECONDS:
        return False
    last_trigger_time[action_name] = now
    return True


# -------------------------------
# Main
# -------------------------------
def main():
    print("=" * 60)
    print("Simple Modbus Video Trigger (merged vid_test + modbus)")
    print("=" * 60)

    # Start VLC RC + preload playlist
    first_path = resolve_video_path(PLAYLIST_ORDER[0])
    if not os.path.exists(first_path):
        log.error(f"First video missing: {first_path}")
        return

    if not start_vlc_controller(first_path):
        return

    if not preload_playlist():
        return

    # Start idle on guide
    switch_video("Guide_steps.mp4")

    # Connect Modbus
    if not connect_modbus():
        print("Could not connect to Modbus PLC")
        return

    print("Monitoring coils 0-4 (rising edge only)... Ctrl+C to exit")
    last_states = [False] * 5

    try:
        while True:
            states = read_coils()
            if states is None:
                log.warning("Read failed, reconnecting Modbus...")
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
                        target = VIDEO_FILES[action_name]
                        log.info(f"Rising edge coil {coil_addr} -> {action_name} -> {target}")
                        switch_video(target)

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
        try:
            if vlc_proc and vlc_proc.poll() is None:
                vlc_proc.terminate()
        except Exception:
            pass
        log.info("Shutdown complete")


if __name__ == "__main__":
    main()
