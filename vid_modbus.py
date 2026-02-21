# export XDG_SESSION_TYPE=x11
# export QT_QPA_PLATFORM=xcb
# python vid_modbus.py

import os
import sys
import time
import threading
import logging
import subprocess
import queue
import shutil
import socket

# Improve VLC stability on Raspberry Pi/Wayland by preferring X11-compatible backend.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    os.environ.setdefault("XDG_SESSION_TYPE", "x11")

# Setup logging to file and console
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_modbus.log")
logging.basicConfig(
    level=logging.INFO,  # Changed from DEBUG to reduce console spam
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Silence pymodbus debug logging in console (still logs to file)
logging.getLogger('pymodbus').setLevel(logging.WARNING)

logger.info("Modbus Video Player started")

# Import Modbus TCP Client
try:
    from pymodbus.client import ModbusTcpClient
    HAS_MODBUS = True
except ImportError:
    logger.error("pymodbus not installed! Install with: pip install pymodbus")
    HAS_MODBUS = False

# Tkinter for GUI
try:
    import tkinter as tk
except ImportError:
    tk = None

def resolve_video_path(filename: str) -> str:
    """Resolve video path for both Pi and Windows runtime."""
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


if sys.platform.startswith("linux"):
    # On Pi/Linux, avoid importing vid.py to prevent in-process libVLC segfaults.
    def init_video_window():
        # Optional only: overlay can interfere with VLC stacking on some Pi setups.
        if os.environ.get("VID_MODBUS_BLACK_OVERLAY", "0") != "1":
            return None

        if tk is None:
            return None
        try:
            root = tk.Tk()
            root.title("Video Background")
            root.configure(bg="black")
            root.minsize(1, 1)

            # Force actual full-screen geometry (more reliable than fullscreen attr alone on Pi).
            root.update_idletasks()
            width = root.winfo_screenwidth()
            height = root.winfo_screenheight()
            root.geometry(f"{width}x{height}+0+0")

            root.overrideredirect(True)
            try:
                root.attributes("-fullscreen", True)
            except Exception:
                pass

            # Keep black background below VLC window so it doesn't overlay videos.
            try:
                root.attributes("-topmost", False)
            except Exception:
                pass

            # Fill full area with explicit black frame.
            bg = tk.Frame(root, bg="black")
            bg.place(x=0, y=0, relwidth=1, relheight=1)

            root.lift()
            root.lower()
            root.bind("<Escape>", lambda _e: root.destroy())
            root.update()
            return root
        except Exception as exc:
            logger.warning(f"Could not create Linux black overlay window: {exc}")
            return None

    def play_video(_):
        return None
else:
    # Import VLC setup from original vid.py (Windows path)
    import importlib.util
    spec = importlib.util.spec_from_file_location("vid_original", os.path.join(os.path.dirname(__file__), "vid.py"))
    if spec and spec.loader:
        vid_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vid_module)
        _setup_vlc_windows = vid_module._setup_vlc_windows
        play_video = vid_module.play_video
        init_video_window = vid_module.init_video_window
    else:
        logger.error("Could not import from vid.py - copy necessary functions manually")
        sys.exit(1)

# =============================================================================
# MODBUS CONFIGURATION
# =============================================================================
MODBUS_SERVER_IP = "192.168.1.100"  # Change to your Siemens LOGO! 8 IP address
MODBUS_SERVER_PORT = int(os.environ.get("MODBUS_SERVER_PORT", "504"))  # Standard Modbus TCP port
MODBUS_UNIT_ID = 1  # Modbus slave/unit ID (typically 1 for LOGO!)
PI_ETH_INTERFACE = "eth0"
PI_IP = "192.168.1.10"
PI_IP_CIDR = f"{PI_IP}/24"

# Modbus coil addresses for video triggers (0-based addressing)
# These map to your 5 GPIO buttons
MODBUS_COILS = {
    "Process_step_1": 0,    # Was GPIO 17
    "Guide_steps": 1,       # Was GPIO 27
    "Warning": 2,           # Was GPIO 22
    "Process_step_2": 3,    # Was GPIO 4
    "Process_step_3": 4,    # Was GPIO 18
}

# Video file mappings
VIDEO_FILES = {
    "Process_step_1": "Process_step_1.mp4",
    "Guide_steps": "Guide_steps.mp4",
    "Warning": "Warning.mp4",
    "Process_step_2": "Process_step_2.mp4",
    "Process_step_3": "Process_step_3.mp4",
}

# Debounce settings
last_trigger_time = {}
for key in MODBUS_COILS.keys():
    last_trigger_time[key] = 0
COOLDOWN_SECONDS = 5  # Minimum seconds between triggers

# Global Modbus client
modbus_client = None
modbus_client_lock = threading.Lock()
modbus_running = False

MODBUS_POLL_INTERVAL_SECONDS = float(os.environ.get("MODBUS_POLL_INTERVAL", "0.2"))
MODBUS_READ_FAILURES_BEFORE_RECONNECT = int(os.environ.get("MODBUS_READ_FAILURES_BEFORE_RECONNECT", "4"))
MODBUS_RECONNECT_DELAY_SECONDS = float(os.environ.get("MODBUS_RECONNECT_DELAY", "1.0"))

# Video playback queue (serialize requests from Modbus thread)
video_queue = queue.Queue(maxsize=20)
video_process_lock = threading.Lock()
guide_vlc_process = None
trigger_vlc_process = None
black_vlc_process = None
USE_EXTERNAL_VLC = sys.platform.startswith("linux")
USE_VLC_RC_CONTROL = False
VLC_RC_HOST = "127.0.0.1"
VLC_RC_PORT = 4213
vlc_supervisor_running = False
video_worker_running = False
trigger_video_active = False
last_requested_video = None
idle_guide_active = False
idle_mode_requested = False
BLACK_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_black.ppm")


def _get_vlc_player_cmd():
    if shutil.which("cvlc"):
        return ["cvlc"]
    if shutil.which("vlc"):
        return ["vlc", "-I", "dummy"]
    return None


def _vlc_fullscreen_base_args():
    """Common VLC args for cleaner fullscreen playback."""
    return [
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-video-deco",
        "--no-qt-fs-controller",
        "--quiet",
    ]


def _force_vlc_window_fullscreen_linux(process_handle):
    """Best-effort X11 window-manager enforcement for borderless fullscreen VLC."""
    if not sys.platform.startswith("linux") or process_handle is None:
        return

    if shutil.which("xdotool") is None:
        return

    pid = str(process_handle.pid)
    deadline = time.time() + 2.5

    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["xdotool", "search", "--pid", pid],
                capture_output=True,
                text=True,
                check=False,
            )
            window_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            if not window_ids:
                time.sleep(0.1)
                continue

            for window_id in window_ids:
                if shutil.which("xprop"):
                    subprocess.run(
                        [
                            "xprop",
                            "-id",
                            window_id,
                            "-f",
                            "_MOTIF_WM_HINTS",
                            "32c",
                            "-set",
                            "_MOTIF_WM_HINTS",
                            "2, 0, 0, 0, 0",
                        ],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

                if shutil.which("wmctrl"):
                    subprocess.run(
                        ["wmctrl", "-i", "-r", window_id, "-b", "remove,maximized_vert,maximized_horz"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                    subprocess.run(
                        ["wmctrl", "-i", "-r", window_id, "-b", "add,fullscreen,above"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )

                subprocess.run(["xdotool", "windowmove", window_id, "0", "0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                subprocess.run(["xdotool", "windowsize", window_id, "100%", "100%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                subprocess.run(["xdotool", "windowraise", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            return
        except Exception:
            time.sleep(0.1)


def _post_launch_fix_vlc_window(process_handle):
    """Run fullscreen/decorations fix asynchronously after VLC spawn."""
    if not sys.platform.startswith("linux"):
        return
    threading.Thread(target=_force_vlc_window_fullscreen_linux, args=(process_handle,), daemon=True).start()


def _prepare_transition_cover_locked():
    """Ensure black cover is visible before any player handoff."""
    if not sys.platform.startswith("linux"):
        return
    hide_terminal_window_linux()
    _ensure_black_screen_loop_locked()
    if black_vlc_process is not None and black_vlc_process.poll() is None:
        _post_launch_fix_vlc_window(black_vlc_process)
    time.sleep(0.08)


def hide_terminal_window_linux():
    """Best-effort minimize of active terminal window on Linux/X11."""
    if not sys.platform.startswith("linux"):
        return

    commands = [
        ["xdotool", "getactivewindow", "windowminimize"],
        ["wmctrl", "-r", ":ACTIVE:", "-b", "add,hidden"],
    ]
    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode == 0:
                logger.info(f"Minimized terminal window using: {' '.join(cmd)}")
                return
        except Exception:
            continue


def _ensure_black_image_file():
    """Create a tiny black image used for fullscreen black background playback."""
    if os.path.exists(BLACK_IMAGE_PATH):
        return
    try:
        with open(BLACK_IMAGE_PATH, "w", encoding="ascii") as file:
            file.write("P3\n1 1\n255\n0 0 0\n")
    except Exception as e:
        logger.warning(f"Could not create black image file: {e}")


def _stop_process_locked(proc):
    if proc is None:
        return None
    try:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.0)
    except Exception:
        pass
    return None


def _send_vlc_command_locked(command):
    """Send command to VLC RC TCP interface. Caller must hold video_process_lock."""
    if not USE_VLC_RC_CONTROL:
        return ""

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(0.35)
    try:
        client.connect((VLC_RC_HOST, VLC_RC_PORT))
        client.sendall((command + "\n").encode("utf-8", errors="ignore"))
        chunks = []
        while True:
            try:
                data = client.recv(4096)
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
            client.close()
        except Exception:
            pass


def _quote_vlc_path(path_value):
    """Quote path for VLC RC commands."""
    return '"' + path_value.replace('"', '\\"') + '"'


def _run_vlc_commands_locked(commands, delay_seconds=0.06):
    """Run RC commands with tiny pacing to avoid command-race drops on Pi."""
    for cmd in commands:
        _send_vlc_command_locked(cmd)
        time.sleep(delay_seconds)


def _wait_for_vlc_socket_locked(timeout_seconds=4.0):
    """Wait until VLC RC TCP interface is available. Caller must hold video_process_lock."""
    if not USE_VLC_RC_CONTROL:
        return True

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if guide_vlc_process and guide_vlc_process.poll() is not None:
            return False
        if _send_vlc_command_locked("status"):
            return True
        time.sleep(0.1)
    return False


def _ensure_external_vlc_running_locked():
    """Ensure persistent external VLC process is running. Caller must hold video_process_lock."""
    player_cmd = _get_vlc_player_cmd()
    if player_cmd is None:
        logger.error("Neither 'cvlc' nor 'vlc' command is available")
        print("Error: Install VLC command-line player (cvlc) on Pi.")
        return False
    return True


def _stop_external_vlc_locked():
    """Stop existing external VLC process. Caller must hold video_process_lock."""
    global guide_vlc_process, trigger_vlc_process, black_vlc_process
    guide_vlc_process = _stop_process_locked(guide_vlc_process)
    trigger_vlc_process = _stop_process_locked(trigger_vlc_process)
    black_vlc_process = _stop_process_locked(black_vlc_process)


def _ensure_black_screen_loop_locked():
    """Ensure persistent black fullscreen process is running."""
    global black_vlc_process

    if black_vlc_process is not None and black_vlc_process.poll() is None:
        return

    _ensure_black_image_file()
    if not os.path.exists(BLACK_IMAGE_PATH):
        logger.error("Black image file is unavailable")
        return

    player_cmd = _get_vlc_player_cmd()
    if player_cmd is None:
        logger.error("Neither 'cvlc' nor 'vlc' command is available")
        return

    black_vlc_process = _stop_process_locked(black_vlc_process)
    cmd = player_cmd + _vlc_fullscreen_base_args() + [
        "--loop",
        "--image-duration", "-1",
        "--no-audio",
        BLACK_IMAGE_PATH,
    ]
    black_vlc_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _post_launch_fix_vlc_window(black_vlc_process)


def _play_idle_guide_locked():
    """Play Guide_steps in loop for idle mode. Caller must hold video_process_lock."""
    global trigger_video_active, guide_vlc_process, black_vlc_process, idle_guide_active, idle_mode_requested
    idle_mode_requested = True
    guide_path = resolve_video_path("Guide_steps.mp4")
    if not os.path.exists(guide_path):
        logger.error(f"Guide video not found: {guide_path}")
        return

    # Avoid restarting VLC if idle guide is already active.
    if (
        (not USE_VLC_RC_CONTROL)
        and idle_guide_active
        and guide_vlc_process is not None
        and guide_vlc_process.poll() is None
    ):
        return

    if USE_VLC_RC_CONTROL:
        _run_vlc_commands_locked([
            "stop",
            "clear",
            "repeat on",
            "loop off",
            f"add {_quote_vlc_path(guide_path)}",
            "play",
        ])

        # Verify idle playback is really running; recover once if not.
        time.sleep(0.2)
        if _vlc_state_locked() != "playing":
            logger.warning("Idle guide did not enter playing state, restarting VLC controller")
            _stop_external_vlc_locked()
            if _ensure_external_vlc_running_locked():
                _run_vlc_commands_locked([
                    "stop",
                    "clear",
                    "repeat on",
                    "loop off",
                    f"add {_quote_vlc_path(guide_path)}",
                    "play",
                ])
    else:
        player_cmd = _get_vlc_player_cmd()
        if player_cmd is None:
            logger.error("Neither 'cvlc' nor 'vlc' command is available")
            return
        _prepare_transition_cover_locked()
        guide_vlc_process = _stop_process_locked(guide_vlc_process)
        cmd = player_cmd + _vlc_fullscreen_base_args() + [
            "--loop",
            "--no-audio",
            guide_path,
        ]
        guide_vlc_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _post_launch_fix_vlc_window(guide_vlc_process)
    trigger_video_active = False
    idle_guide_active = True
    logger.info("Idle guide loop active")


def _play_trigger_once_locked(video_file):
    """Play requested trigger video once. Caller must hold video_process_lock."""
    global trigger_video_active, trigger_vlc_process, guide_vlc_process, black_vlc_process, last_requested_video, idle_guide_active, idle_mode_requested
    video_path = resolve_video_path(video_file)
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        print(f"Error: Video file not found: {video_path}")
        return

    if USE_VLC_RC_CONTROL:
        _run_vlc_commands_locked([
            "stop",
            "clear",
            "repeat off",
            "loop off",
            f"add {_quote_vlc_path(video_path)}",
            "play",
        ])

        # Verify trigger playback is really active; restart and retry once if needed.
        time.sleep(0.25)
        if _vlc_state_locked() != "playing":
            logger.warning(f"Trigger switch failed for {video_file}, restarting VLC and retrying")
            _stop_external_vlc_locked()
            if _ensure_external_vlc_running_locked():
                _run_vlc_commands_locked([
                    "stop",
                    "clear",
                    "repeat off",
                    "loop off",
                    f"add {_quote_vlc_path(video_path)}",
                    "play",
                ])
    else:
        player_cmd = _get_vlc_player_cmd()
        if player_cmd is None:
            logger.error("Neither 'cvlc' nor 'vlc' command is available")
            return

        # Any non-guide trigger cancels idle guide mode until guide is explicitly requested again.
        idle_mode_requested = False

        # Keep black cover visible before and during transition.
        _prepare_transition_cover_locked()

        # Idle guide must not overlap with a trigger video.
        guide_vlc_process = _stop_process_locked(guide_vlc_process)
        idle_guide_active = False

        previous_trigger = trigger_vlc_process
        cmd = player_cmd + _vlc_fullscreen_base_args() + [
            "--play-and-exit",
            "--no-audio",
            video_path,
        ]
        new_trigger = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _post_launch_fix_vlc_window(new_trigger)
        trigger_vlc_process = new_trigger
        previous_trigger = _stop_process_locked(previous_trigger)
    trigger_video_active = True
    idle_guide_active = False
    last_requested_video = video_file
    logger.info(f"Switched to trigger video: {video_file}")
    print(f"Switched to: {video_file}")


def _vlc_state_locked():
    """Read VLC state from RC interface. Caller must hold video_process_lock."""
    if not USE_VLC_RC_CONTROL:
        if trigger_vlc_process is not None and trigger_vlc_process.poll() is None:
            return "playing"
        if guide_vlc_process is not None and guide_vlc_process.poll() is None:
            return "playing"
        if black_vlc_process is not None and black_vlc_process.poll() is None:
            return "playing"
        if trigger_vlc_process is None and guide_vlc_process is None:
            return "stopped"
        return "stopped"

    status = _send_vlc_command_locked("status")
    lowered = status.lower()
    if "state playing" in lowered:
        return "playing"
    if "state paused" in lowered:
        return "paused"
    if "state stopped" in lowered:
        return "stopped"
    return "unknown"


def vlc_supervisor_loop():
    """Keep VLC alive and ensure guide loops during idle."""
    global vlc_supervisor_running, trigger_video_active, idle_guide_active, trigger_vlc_process
    logger.info("VLC supervisor started")
    while vlc_supervisor_running:
        if not USE_EXTERNAL_VLC:
            time.sleep(0.5)
            continue

        try:
            with video_process_lock:
                if not _ensure_external_vlc_running_locked():
                    time.sleep(0.6)
                    continue

                # In non-RC mode, detect trigger completion by trigger process exit.
                if (not USE_VLC_RC_CONTROL) and trigger_video_active:
                    if trigger_vlc_process is None or trigger_vlc_process.poll() is not None:
                        trigger_video_active = False
                        idle_guide_active = False
                        trigger_vlc_process = _stop_process_locked(trigger_vlc_process)

                state = _vlc_state_locked()
                # If a trigger finished (stopped), immediately return to looping guide.
                if trigger_video_active and state == "stopped":
                    if idle_mode_requested:
                        _play_idle_guide_locked()
                    else:
                        _ensure_black_screen_loop_locked()
                # Ensure idle guide is always active when nothing is playing.
                elif (not trigger_video_active) and state == "stopped":
                    if idle_mode_requested:
                        _play_idle_guide_locked()
                    else:
                        _ensure_black_screen_loop_locked()
                # Unknown often means RC transient; make sure something is still visible.
                elif state == "unknown" and not trigger_video_active:
                    if idle_mode_requested:
                        _play_idle_guide_locked()
                    else:
                        _ensure_black_screen_loop_locked()

                # Keep black background persistent when guide mode is not requested.
                if (not trigger_video_active) and (not idle_mode_requested):
                    _ensure_black_screen_loop_locked()
        except Exception as e:
            logger.warning(f"VLC supervisor warning: {e}")

        time.sleep(0.1)


def play_video_safe(video_file):
    """Play video robustly; Linux uses external VLC process to avoid libVLC segfaults."""
    if not USE_EXTERNAL_VLC:
        play_video(video_file)
        return

    with video_process_lock:
        if not _ensure_external_vlc_running_locked():
            return
        if video_file == "Guide_steps.mp4":
            _play_idle_guide_locked()
        else:
            _play_trigger_once_locked(video_file)


def queue_video_play(video_file):
    """Queue a video request; keep latest requests flowing without blocking."""
    try:
        video_queue.put_nowait(video_file)
    except queue.Full:
        try:
            video_queue.get_nowait()  # drop oldest
            video_queue.put_nowait(video_file)
        except Exception:
            logger.warning("Video queue full; dropping request")


def video_playback_worker():
    """Single worker that executes play_video to avoid concurrent VLC switches."""
    global video_worker_running
    logger.info("Video playback worker started")
    while video_worker_running:
        video_file = None
        try:
            video_file = video_queue.get(timeout=0.3)
            play_video_safe(video_file)
        except queue.Empty:
            continue
        except Exception as e:
            logger.error(f"Video playback worker error: {e}")
        finally:
            if video_file is not None:
                video_queue.task_done()

# =============================================================================
# MODBUS FUNCTIONS
# =============================================================================

def connect_modbus():
    """Connect to the Siemens LOGO! 8 PLC via Modbus TCP"""
    global modbus_client
    try:
        # Ensure Pi Ethernet IP is configured before Modbus TCP connect
        if not ensure_pi_ip_for_modbus():
            logger.error("Required Pi Ethernet IP is not configured")
            return False

        with modbus_client_lock:
            if modbus_client:
                try:
                    modbus_client.close()
                except Exception:
                    pass

            logger.info(f"Connecting to Modbus server at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
            modbus_client = ModbusTcpClient(
                MODBUS_SERVER_IP,
                port=MODBUS_SERVER_PORT,
                timeout=2,
            )

            if modbus_client.connect():
                logger.info("Successfully connected to Modbus server")
                return True

        logger.error("Failed to connect to Modbus server")
        return False
    except Exception as e:
        logger.error(f"Modbus connection error: {e}")
        return False


def _read_coils_with_unit_id(client, start_addr, count):
    """Read coils while handling pymodbus API differences for unit/slave/device_id."""
    try:
        return client.read_coils(start_addr, count=count, device_id=MODBUS_UNIT_ID)
    except TypeError:
        try:
            return client.read_coils(start_addr, count=count, slave=MODBUS_UNIT_ID)
        except TypeError:
            return client.read_coils(start_addr, count=count, unit=MODBUS_UNIT_ID)


def _interface_has_ip(interface_name, ip_address):
    """Return True if interface already has the target IPv4 address."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", interface_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return ip_address in result.stdout
    except Exception:
        return False


def ensure_pi_ip_for_modbus():
    """Ensure eth0 has 192.168.1.10/24 before trying Modbus connection."""
    if not sys.platform.startswith("linux"):
        logger.info("Skipping IP setup (non-Linux platform)")
        return True

    if _interface_has_ip(PI_ETH_INTERFACE, PI_IP):
        logger.info(f"{PI_ETH_INTERFACE} already has {PI_IP_CIDR}")
        print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
        return True

    print(f"Configuring network: assigning {PI_IP_CIDR} to {PI_ETH_INTERFACE}...")
    logger.info(f"Assigning {PI_IP_CIDR} to {PI_ETH_INTERFACE}")

    commands = [
        ["ip", "addr", "add", PI_IP_CIDR, "dev", PI_ETH_INTERFACE],
        ["sudo", "-n", "ip", "addr", "add", PI_IP_CIDR, "dev", PI_ETH_INTERFACE],
    ]

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = (result.stdout or "") + (result.stderr or "")

            if result.returncode == 0:
                logger.info(f"IP assignment successful using: {' '.join(cmd)}")
                print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
                return True

            if "Address already assigned" in output:
                logger.info(f"IP already assigned on {PI_ETH_INTERFACE}")
                print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
                return True

        except FileNotFoundError:
            logger.warning(f"Command not found: {' '.join(cmd)}")
            continue
        except Exception as exc:
            logger.warning(f"Error running {' '.join(cmd)}: {exc}")

    # Final verification after command attempts
    if _interface_has_ip(PI_ETH_INTERFACE, PI_IP):
        print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
        return True

    print("\nCould not auto-configure Pi Ethernet IP for Modbus.")
    print(f"Run this once before starting: sudo ip addr add {PI_IP_CIDR} dev {PI_ETH_INTERFACE}")
    print("If it says 'Address already assigned', that is OK.")
    return False


def read_modbus_coils():
    """Read all configured coils from the PLC and return their states"""
    global modbus_client
    with modbus_client_lock:
        client = modbus_client

    if not client:
        logger.warning("Modbus client not connected")
        return None
    
    try:
        # Read 5 coils starting from address 0
        result = _read_coils_with_unit_id(client, 0, 5)
        
        if result.isError():
            logger.error(f"Error reading coils: {result}")
            return None
        
        return result.bits[:5]  # Return first 5 coil states
    
    except Exception as e:
        logger.error(f"Exception reading Modbus coils: {e}")
        with modbus_client_lock:
            if modbus_client:
                try:
                    modbus_client.close()
                except Exception:
                    pass
                modbus_client = None
        return None


def can_trigger_action(action_name):
    """Check if enough time has passed since last trigger (debounce)"""
    current_time = time.time()
    time_since_last = current_time - last_trigger_time[action_name]
    
    if time_since_last < COOLDOWN_SECONDS:
        return False
    
    last_trigger_time[action_name] = current_time
    return True


def handle_modbus_trigger(action_name):
    """Handle a Modbus trigger by playing the appropriate video"""
    if can_trigger_action(action_name):
        video_file = VIDEO_FILES[action_name]
        logger.info(f"Modbus trigger: {action_name} -> {video_file}")
        print(f"  -> Playing video: {video_file}")
        queue_video_play(video_file)
    else:
        logger.debug(f"Trigger for {action_name} ignored (cooldown active)")
        print(f"  -> Trigger ignored (cooldown: {COOLDOWN_SECONDS}s)")


def modbus_polling_loop():
    """Main loop that polls Modbus coils and triggers videos"""
    global modbus_running
    logger.info("Starting Modbus polling loop")
    print("[Modbus Monitor] Polling started - waiting for coil changes...\n")
    
    # Track last state of each coil to detect rising edge (0 -> 1 transition)
    last_coil_states = [False] * 5
    consecutive_read_failures = 0

    while modbus_running:
        try:
            # Read current coil states
            coil_states = read_modbus_coils()
            
            if coil_states is None:
                consecutive_read_failures += 1
                if consecutive_read_failures >= MODBUS_READ_FAILURES_BEFORE_RECONNECT:
                    logger.warning(
                        f"Modbus read failed {consecutive_read_failures} times; reconnecting..."
                    )
                    time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
                    if connect_modbus():
                        last_coil_states = [False] * 5
                        consecutive_read_failures = 0
                        hide_terminal_window_linux()
                    else:
                        time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
                else:
                    time.sleep(MODBUS_POLL_INTERVAL_SECONDS)
                continue

            consecutive_read_failures = 0
            
            # Check each coil for rising edge (transition from False to True)
            for idx, (action_name, coil_addr) in enumerate(MODBUS_COILS.items()):
                current_state = coil_states[idx]
                previous_state = last_coil_states[idx]
                
                # Trigger on rising edge (0 -> 1)
                if current_state and not previous_state:
                    logger.info(f"Rising edge detected on coil {coil_addr} ({action_name})")
                    print(f"[Coil {coil_addr}] State changed: OFF -> ON ({action_name})")
                    handle_modbus_trigger(action_name)
                # Also log falling edge for visibility
                elif not current_state and previous_state:
                    logger.info(f"Falling edge detected on coil {coil_addr} ({action_name})")
                    print(f"[Coil {coil_addr}] State changed: ON -> OFF ({action_name})")
                
                # Update last state
                last_coil_states[idx] = current_state
            
            time.sleep(MODBUS_POLL_INTERVAL_SECONDS)
            
        except KeyboardInterrupt:
            logger.info("Modbus polling interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in Modbus polling loop: {e}")
            time.sleep(MODBUS_RECONNECT_DELAY_SECONDS)
    
    # Cleanup
    with modbus_client_lock:
        if modbus_client:
            modbus_client.close()
            logger.info("Modbus connection closed")


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main():
    global vlc_supervisor_running, idle_mode_requested, modbus_running, video_worker_running
    logger.info("=== Modbus Video Player Startup ===")
    logger.info(f"Modbus Server: {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
    logger.info(f"Configured coils: {MODBUS_COILS}")
    
    if not HAS_MODBUS:
        logger.error("Cannot run without pymodbus. Install it with: pip install pymodbus")
        print("\nERROR: pymodbus not installed!")
        print("Install it with: pip install pymodbus")
        return

    # Ensure Pi Ethernet IP is configured before Modbus TCP connect
    if not ensure_pi_ip_for_modbus():
        logger.error("Required Pi Ethernet IP is not configured")
        return
    
    # Connect to Modbus server
    print("=" * 60)
    print(f"Connecting to Modbus PLC at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}...")
    print("=" * 60)
    
    if not connect_modbus():
        logger.error("Failed to establish initial Modbus connection")
        print("\n" + "=" * 60)
        print("ERROR: MODBUS CONNECTION FAILED")
        print("=" * 60)
        print(f"Could not connect to {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
        print("\nPlease check:")
        print("  1. PLC is powered on")
        print("  2. Ethernet cable is connected")
        print("  3. Pi has IP 192.168.1.10 (run: ip -4 addr show dev eth0)")
        print("  4. PLC IP is correct: 192.168.1.100")
        print("  5. Modbus TCP is enabled on the LOGO! 8")
        print("=" * 60)
        return
    
    # Connection successful
    print("\n" + "=" * 60)
    print("✓ MODBUS CONNECTION SUCCESSFUL!")
    print("=" * 60)
    print(f"Connected to PLC at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
    print("Monitoring coils 0-4 for state changes...")
    print("=" * 60 + "\n")

    # Hide terminal window to avoid visible desktop/terminal flashes during video switches.
    hide_terminal_window_linux()
    
    # Create GUI window (black fullscreen on Pi, embedded on Windows)
    root = init_video_window()

    # Start playback worker thread (serializes all play requests)
    video_worker_running = True
    playback_thread = threading.Thread(target=video_playback_worker, daemon=True)
    playback_thread.start()

    # Keep persistent VLC alive and force idle guide loop when no trigger video is active
    if USE_EXTERNAL_VLC:
        vlc_supervisor_running = True
        supervisor_thread = threading.Thread(target=vlc_supervisor_loop, daemon=True)
        supervisor_thread.start()

    # Start with guide video in idle mode on launch
    logger.info("Starting with guide idle video")
    with video_process_lock:
        idle_mode_requested = True
        _play_idle_guide_locked()
    
    # Start Modbus polling in background thread
    modbus_running = True
    modbus_thread = threading.Thread(target=modbus_polling_loop, daemon=True)
    modbus_thread.start()
    logger.info("Modbus polling thread started")
    
    # Run GUI main loop (if available)
    if root is not None:
        logger.info("Starting GUI main loop")
        try:
            root.mainloop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    else:
        # No GUI - just wait for Modbus triggers
        logger.info("Running without GUI (console mode)")
        print("Press Ctrl+C to exit")
        try:
            modbus_thread.join()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    
    # Cleanup
    modbus_running = False
    video_worker_running = False
    vlc_supervisor_running = False

    try:
        modbus_thread.join(timeout=2)
    except Exception:
        pass
    try:
        playback_thread.join(timeout=2)
    except Exception:
        pass

    if USE_EXTERNAL_VLC:
        with video_process_lock:
            _stop_external_vlc_locked()

    with modbus_client_lock:
        if modbus_client:
            modbus_client.close()
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
