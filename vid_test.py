# export XDG_SESSION_TYPE=x11
# export QT_QPA_PLATFORM=xcb
# python vid_test.py

import os
import sys
import time
import threading
import logging
import subprocess
import shutil
import socket

if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    os.environ.setdefault("XDG_SESSION_TYPE", "x11")

log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_vid_test.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

VIDEO_SEQUENCE = [
    "Guide_steps.mp4",
    "Process_step_1.mp4",
    "Warning.mp4",
    "Process_step_2.mp4",
    "Process_step_3.mp4",
]

SWITCH_INTERVAL_SECONDS = float(os.environ.get("VID_TEST_INTERVAL_SECONDS", "5"))
TERMINAL_GUARD_INTERVAL_SECONDS = float(os.environ.get("VID_TEST_TERMINAL_GUARD_SECONDS", "0.08"))
VLC_RC_HOST = os.environ.get("VID_TEST_VLC_RC_HOST", "127.0.0.1")
VLC_RC_PORT = int(os.environ.get("VID_TEST_VLC_RC_PORT", "4215"))

terminal_guard_running = False
vlc_controller_process = None
TERMINAL_WINDOW_CLASSES = [
    "lxterminal",
    "xfce4-terminal",
    "gnome-terminal",
    "xterm",
    "qterminal",
    "konsole",
    "mate-terminal",
]


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


def _get_vlc_player_cmd():
    if shutil.which("cvlc"):
        return ["cvlc"]
    if shutil.which("vlc"):
        return ["vlc", "-I", "dummy"]
    return None


def _stop_process(proc):
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


def hide_terminal_window_linux():
    if not sys.platform.startswith("linux"):
        return

    quick_cmds = [
        ["xdotool", "getactivewindow", "windowminimize"],
        ["wmctrl", "-r", ":ACTIVE:", "-b", "add,hidden"],
    ]
    for cmd in quick_cmds:
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=False)
        except Exception:
            pass

    if shutil.which("xdotool") is None:
        return

    for class_name in TERMINAL_WINDOW_CLASSES:
        try:
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--class", class_name],
                capture_output=True,
                text=True,
                check=False,
            )
            window_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            for window_id in window_ids:
                subprocess.run(["xdotool", "windowminimize", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except Exception:
            continue


def terminal_guard_loop():
    global terminal_guard_running
    if not sys.platform.startswith("linux"):
        return
    while terminal_guard_running:
        hide_terminal_window_linux()
        time.sleep(TERMINAL_GUARD_INTERVAL_SECONDS)


def _send_vlc_command(command: str, timeout_seconds: float = 0.35) -> str:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
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


def _wait_for_vlc_rc(timeout_seconds: float = 6.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if vlc_controller_process and vlc_controller_process.poll() is not None:
            return False
        if _send_vlc_command("status"):
            return True
        time.sleep(0.1)
    return False


def _quote_path(path_value: str) -> str:
    return '"' + path_value.replace('"', '\\"') + '"'


def _start_vlc_controller() -> bool:
    global vlc_controller_process
    player_cmd = _get_vlc_player_cmd()
    if player_cmd is None:
        logger.error("Neither 'cvlc' nor 'vlc' command is available")
        return False

    vlc_controller_process = _stop_process(vlc_controller_process)
    cmd = player_cmd + [
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-video-deco",
        "--no-qt-fs-controller",
        "--quiet",
        "--no-audio",
        "--extraintf", "rc",
        "--rc-host", f"{VLC_RC_HOST}:{VLC_RC_PORT}",
    ]
    vlc_controller_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return _wait_for_vlc_rc()


def _preload_playlist(video_paths):
    _send_vlc_command("stop")
    _send_vlc_command("clear")
    for path in video_paths:
        _send_vlc_command(f"enqueue {_quote_path(path)}")
        time.sleep(0.03)
    _send_vlc_command("stop")


def _switch_to_preloaded_index(index: int, name: str):
    hide_terminal_window_linux()
    _send_vlc_command(f"goto {index}")
    _send_vlc_command("seek 0")
    _send_vlc_command("play")
    logger.info(f"Switched to: {name} (index {index})")


def main():
    global terminal_guard_running, vlc_controller_process

    logger.info("=== Timed Video Test Started ===")
    logger.info(f"Switch interval: {SWITCH_INTERVAL_SECONDS}s")
    logger.info(f"Sequence: {VIDEO_SEQUENCE}")

    if not sys.platform.startswith("linux"):
        logger.error("vid_test.py is intended for Raspberry Pi/Linux.")
        return

    resolved_sequence = []
    for video_name in VIDEO_SEQUENCE:
        path = resolve_video_path(video_name)
        if not os.path.exists(path):
            logger.warning(f"Missing video, skipped: {path}")
            continue
        resolved_sequence.append((video_name, path))

    if not resolved_sequence:
        logger.error("No valid videos found in sequence")
        return

    terminal_guard_running = True
    terminal_guard_thread = threading.Thread(target=terminal_guard_loop, daemon=True)
    terminal_guard_thread.start()

    try:
        if not _start_vlc_controller():
            logger.error("Could not start VLC RC controller")
            return

        _preload_playlist([path for _, path in resolved_sequence])
        logger.info("Preloaded all videos at startup")

        index = 0
        while True:
            name, _path = resolved_sequence[index % len(resolved_sequence)]
            _switch_to_preloaded_index(index % len(resolved_sequence), name)
            index += 1
            time.sleep(SWITCH_INTERVAL_SECONDS)

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        terminal_guard_running = False
        try:
            terminal_guard_thread.join(timeout=1)
        except Exception:
            pass

        vlc_controller_process = _stop_process(vlc_controller_process)
        logger.info("vid_test shutdown complete")


if __name__ == "__main__":
    main()
