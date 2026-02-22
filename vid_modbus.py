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
PLAYLIST_INDEX = {}  # built at runtime from actually loaded files (0-based positions)
AVAILABLE_VIDEO_PATHS = {}
ACTIVE_PLAYLIST = []
current_playlist_index = 0

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
VLC_LOG_FILE = os.environ.get("VLC_LOG_FILE", "vlc_startup.log")

modbus_client = None
last_trigger_time = {key: 0.0 for key in MODBUS_COILS}
read_fail_streak = 0


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


def cleanup_existing_vlc():
    if not sys.platform.startswith("linux"):
        return

    patterns = [
        f"cvlc.*--rc-host {RC_HOST}:{RC_PORT}",
        f"vlc.*--rc-host {RC_HOST}:{RC_PORT}",
    ]
    for pattern in patterns:
        try:
            subprocess.run(["pkill", "-f", pattern], capture_output=True, text=True, check=False)
        except Exception:
            pass
    time.sleep(0.2)


def verify_x11_access() -> bool:
    if not sys.platform.startswith("linux"):
        return True

    display = os.environ.get("DISPLAY", ":0")
    env = os.environ.copy()

    probe_cmds = [
        ["xdpyinfo", "-display", display],
        ["xset", "q"],
    ]

    for cmd in probe_cmds:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
            if result.returncode == 0:
                log.info(f"X11 probe OK via: {' '.join(cmd)}")
                print(f"X11 probe OK via: {' '.join(cmd)}")
                return True
        except Exception:
            continue

    log.error("X11 probe failed (cannot query active display)")
    print("X11 probe failed (cannot query active display)")
    return False


def force_vlc_window_visible(attempts: int = 20, delay: float = 0.15):
    if not sys.platform.startswith("linux"):
        return

    for _ in range(attempts):
        try:
            result = subprocess.run(
                ["xdotool", "search", "--class", "vlc"],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and result.stdout.strip():
                ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
                for wid in ids[-3:]:
                    subprocess.run(["xdotool", "windowmap", wid], capture_output=True, text=True, check=False)
                    subprocess.run(["xdotool", "windowraise", wid], capture_output=True, text=True, check=False)
                    subprocess.run(["xdotool", "windowactivate", "--sync", wid], capture_output=True, text=True, check=False)
                    subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "add,above,fullscreen"], capture_output=True, text=True, check=False)

                log.info("VLC window activated/raised")
                print("VLC window activated/raised")
                return
        except Exception:
            pass

        time.sleep(delay)

    try:
        subprocess.run(["wmctrl", "-a", "VLC media player"], capture_output=True, text=True, check=False)
    except Exception:
        pass


def start_vlc(dummy_video: str):
    if not shutil.which("cvlc"):
        log.error("cvlc not installed")
        sys.exit(1)

    cleanup_existing_vlc()

    cmd = [
        "cvlc",
        "--intf", "dummy",
        "--extraintf", "rc",
        "--rc-host", f"{RC_HOST}:{RC_PORT}",
        "--x11-display", os.environ.get("DISPLAY", ":0"),
        "--vout", "x11",
        "--avcodec-hw=none",
        "--no-embedded-video",
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
    print(f"Launching VLC RC controller (log: {VLC_LOG_FILE})")

    vlc_log = open(VLC_LOG_FILE, "a", buffering=1)
    vlc_log.write("\n=== VLC launch ===\n")
    vlc_log.write("Command: " + " ".join(cmd) + "\n")
    vlc_log.write(f"DISPLAY={os.environ.get('DISPLAY')} XAUTHORITY={os.environ.get('XAUTHORITY')}\n")

    subprocess.Popen(
        cmd,
        stdout=vlc_log,
        stderr=vlc_log,
        env=os.environ.copy(),
        start_new_session=True,
    )

    if not wait_for_rc():
        log.error("VLC RC interface did not respond")
        sys.exit(1)

    # Make sure VLC surface is visible even when launched from different terminals/sessions.
    force_vlc_window_visible()


def build_playlist(video_paths):
    # EXACT same method pattern as vid_test
    global current_playlist_index
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
    current_playlist_index = 0


def rebuild_playlist_index(video_paths):
    global PLAYLIST_INDEX
    global ACTIVE_PLAYLIST
    PLAYLIST_INDEX = {}
    ACTIVE_PLAYLIST = [os.path.basename(path) for path in video_paths]
    for idx, full_path in enumerate(video_paths):
        name = os.path.basename(full_path)
        PLAYLIST_INDEX[name] = idx

    mapping = ", ".join(f"{k}:{v}" for k, v in PLAYLIST_INDEX.items())
    log.info(f"Playlist index: {mapping}")
    print(f"Playlist index: {mapping}")


def switch_to_video(video_file: str):
    print(f"Switch request: {video_file}")
    target_path = AVAILABLE_VIDEO_PATHS.get(video_file)
    if not target_path:
        log.error(f"Target not available: {video_file}")
        print(f"Target not available: {video_file}")
        return

    rc("stop")
    rc("clear")
    if video_file in ("Guide_steps.mp4", "Warning.mp4"):
        rc("repeat on")
    else:
        rc("repeat off")
    rc("loop off")
    rc("random off")
    rc(f"add {target_path}")
    time.sleep(0.08)
    rc("seek 0")
    rc("play")
    rc("fullscreen on")

    force_vlc_window_visible()
    log.info(f"Switched to: {video_file}")
    print(f"Switched to: {video_file}")


def start_guide_idle():
    """Force guide video to become visible immediately at startup."""
    print("Startup: forcing Guide_steps.mp4 on screen")
    log.info("Startup: forcing Guide_steps.mp4 on screen")

    ok = False
    for _ in range(3):
        switch_to_video("Guide_steps.mp4")
        ok = True
        if ok:
            break
        time.sleep(0.2)

    if ok:
        force_vlc_window_visible()
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
        # Match known-stable modbus_test.py behavior.
        result = modbus_client.read_coils(0, count=5)

        if result.isError():
            log.warning(f"Modbus read error response: {result}")
            return None
        return result.bits[:5]
    except Exception as e:
        log.warning(f"Modbus read exception: {e}")
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

    if not verify_x11_access():
        print("Startup aborted: X11 display is not accessible from this terminal session")
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
    global read_fail_streak
    read_fail_streak = 0

    try:
        while True:
            states = read_coils()
            if states is None:
                read_fail_streak += 1
                if read_fail_streak >= 5:
                    log.warning("Modbus read failed repeatedly, reconnecting...")
                    print("Modbus read failed repeatedly, reconnecting...")
                    time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
                    connect_modbus()
                    read_fail_streak = 0
                    time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
                else:
                    time.sleep(MODBUS_POLL_INTERVAL_SECONDS)
                continue

            read_fail_streak = 0

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
