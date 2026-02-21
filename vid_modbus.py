#!/usr/bin/env python3
import os
import time
import socket
import subprocess
import shutil
import sys
import logging
import pwd

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
os.environ["DISPLAY"] = os.environ.get("DISPLAY", ":0")
os.environ["XDG_SESSION_TYPE"] = "x11"
os.environ["QT_QPA_PLATFORM"] = "xcb"


def _resolve_user_home(username: str):
    try:
        return pwd.getpwnam(username).pw_dir
    except Exception:
        return None


def configure_x11_auth():
    xauth_candidates = []

    env_xauth = os.environ.get("XAUTHORITY")
    if env_xauth:
        xauth_candidates.append(env_xauth)

    candidate_users = []
    for key in ("SUDO_USER", "USER", "LOGNAME"):
        value = os.environ.get(key)
        if value and value not in candidate_users:
            candidate_users.append(value)

    # Prefer sudo-invoker desktop user when script is run with sudo.
    for user in candidate_users:
        home_dir = _resolve_user_home(user)
        if home_dir:
            xauth_candidates.append(os.path.join(home_dir, ".Xauthority"))

    # Fallbacks
    xauth_candidates.append(os.path.join(os.path.expanduser("~"), ".Xauthority"))
    xauth_candidates.append("/home/pi/.Xauthority")
    xauth_candidates.append("/home/helmwash/.Xauthority")

    chosen = None
    for path in xauth_candidates:
        if path and os.path.exists(path):
            chosen = path
            break

    if chosen:
        os.environ["XAUTHORITY"] = chosen
        log.info(f"X11 env: DISPLAY={os.environ.get('DISPLAY')} XAUTHORITY={chosen}")
        print(f"X11 env: DISPLAY={os.environ.get('DISPLAY')} XAUTHORITY={chosen}")
        return True

    log.error("No usable .Xauthority found for GUI session")
    print("No usable .Xauthority found for GUI session")
    return False

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
PLAYLIST_INDEX = {}  # built at runtime from actually loaded files (VLC goto is 1-based)
AVAILABLE_VIDEO_PATHS = {}

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

ETH_INTERFACE = os.environ.get("ETH_INTERFACE", "eth0")
PI_STATIC_IP_CIDR = os.environ.get("PI_STATIC_IP_CIDR", "192.168.1.10/24")
PLC_PING_IP = os.environ.get("PLC_PING_IP", "192.168.1.100")

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
    rc("loop off")
    rc("random off")

    rc(f"add {video_paths[0]}")
    time.sleep(0.1)
    for v in video_paths[1:]:
        rc(f"enqueue {v}")
        time.sleep(0.05)

    rc("seek 0")
    rc("play")
    rc("fullscreen on")


def rebuild_playlist_index(video_paths):
    global PLAYLIST_INDEX
    PLAYLIST_INDEX = {}
    for idx, full_path in enumerate(video_paths, start=1):
        name = os.path.basename(full_path)
        PLAYLIST_INDEX[name] = idx

    mapping = ", ".join(f"{k}:{v}" for k, v in PLAYLIST_INDEX.items())
    log.info(f"Playlist index: {mapping}")
    print(f"Playlist index: {mapping}")


def rebuild_switch_playlist(target_video_file: str):
    target_path = AVAILABLE_VIDEO_PATHS.get(target_video_file)
    if not target_path:
        log.error(f"Target not available: {target_video_file}")
        print(f"Target not available: {target_video_file}")
        return False

    ordered = [target_path]
    for name in VIDEOS:
        if name == target_video_file:
            continue
        other_path = AVAILABLE_VIDEO_PATHS.get(name)
        if other_path:
            ordered.append(other_path)

    rc("stop")
    rc("clear")
    rc("random off")
    rc("loop off")
    if target_video_file in ("Guide_steps.mp4", "Warning.mp4"):
        rc("repeat on")
    else:
        rc("repeat off")

    rc(f"add {ordered[0]}")
    time.sleep(0.1)
    for v in ordered[1:]:
        rc(f"enqueue {v}")
        time.sleep(0.05)

    rc("seek 0")
    rc("play")
    rc("fullscreen on")
    return True


def switch_to_video(video_file: str):
    print(f"Switch request: {video_file}")
    ok = rebuild_switch_playlist(video_file)
    if ok:
        log.info(f"Switched to: {video_file}")
        print(f"Switched to: {video_file}")
    else:
        log.error(f"Switch failed: {video_file}")
        print(f"Switch failed: {video_file}")


def start_guide_idle():
    """Force guide video to become visible immediately at startup."""
    print("Startup: forcing Guide_steps.mp4 on screen")
    log.info("Startup: forcing Guide_steps.mp4 on screen")

    ok = False
    for _ in range(3):
        ok = rebuild_switch_playlist("Guide_steps.mp4")
        if ok:
            break
        time.sleep(0.2)

    if ok:
        log.info("Guide startup asserted")
        print("Guide startup asserted")
    else:
        log.error("Guide startup failed")
        print("Guide startup failed")


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


def ensure_network_ready() -> bool:
    """Apply required Ethernet setup and verify PLC reachability."""
    if not sys.platform.startswith("linux"):
        return True

    commands = [
        ["ip", "addr", "add", PI_STATIC_IP_CIDR, "dev", ETH_INTERFACE],
        ["sudo", "-n", "ip", "addr", "add", PI_STATIC_IP_CIDR, "dev", ETH_INTERFACE],
    ]

    addr_ok = False
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = ((result.stdout or "") + (result.stderr or "")).lower()
            if result.returncode == 0 or "file exists" in output or "address already assigned" in output:
                addr_ok = True
                break
        except Exception:
            continue

    if not addr_ok:
        log.error(f"Failed to apply IP {PI_STATIC_IP_CIDR} on {ETH_INTERFACE}")
        return False

    link_ok = False
    link_cmds = [
        ["ip", "link", "set", ETH_INTERFACE, "up"],
        ["sudo", "-n", "ip", "link", "set", ETH_INTERFACE, "up"],
    ]
    for cmd in link_cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                link_ok = True
                break
        except Exception:
            continue

    if not link_ok:
        log.error(f"Failed to bring interface up: {ETH_INTERFACE}")
        return False

    # Required command equivalent: ping 192.168.1.100
    ping_ok = False
    ping_cmds = [
        ["ping", "-c", "1", PLC_PING_IP],
        ["ping", "-c", "3", PLC_PING_IP],
    ]
    for cmd in ping_cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                ping_ok = True
                break
        except Exception:
            continue

    if not ping_ok:
        log.warning(f"Ping failed to PLC {PLC_PING_IP}; continuing to Modbus connect attempt")
    else:
        log.info(f"Network ready on {ETH_INTERFACE}: {PI_STATIC_IP_CIDR}, PLC ping OK ({PLC_PING_IP})")

    return True


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
    print("Starting vid_modbus...")
    print(f"Runtime user info: uid={os.getuid()} user={os.environ.get('USER')} sudo_user={os.environ.get('SUDO_USER')}")

    if not configure_x11_auth():
        print("Startup aborted: no X11 authorization available")
        return

    global AVAILABLE_VIDEO_PATHS
    AVAILABLE_VIDEO_PATHS = {}
    video_paths = []
    for v in VIDEOS:
        p = os.path.abspath(resolve_video_path(v))
        if os.path.exists(p):
            video_paths.append(p)
            AVAILABLE_VIDEO_PATHS[v] = p
        else:
            log.warning(f"Missing video: {p}")

    if not video_paths:
        log.error("No valid videos found")
        print("No valid videos found")
        return

    # Startup VLC + playlist with same method as vid_test
    print("Startup: launching VLC")
    start_vlc(video_paths[0])
    print("Startup: building playlist")
    build_playlist(video_paths)
    rebuild_playlist_index(video_paths)

    # Start on guide immediately and keep it visible until a trigger arrives
    start_guide_idle()

    if not ensure_network_ready():
        print("Could not configure Ethernet network for PLC")
        return

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
