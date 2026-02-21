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
    os.environ.setdefault("DISPLAY", ":0")
    home_auth = os.path.join(os.path.expanduser("~"), ".Xauthority")
    if os.path.exists(home_auth):
        os.environ.setdefault("XAUTHORITY", home_auth)

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
VLC_RC_PORT_FALLBACK_COUNT = int(os.environ.get("VID_TEST_VLC_RC_PORT_FALLBACK_COUNT", "4"))

terminal_guard_running = False
vlc_controller_process = None
vlc_rc_port_in_use = VLC_RC_PORT
current_playlist_index = 0
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
    # Prefer full VLC binary for reliable window/video output.
    if shutil.which("vlc"):
        return ["vlc"]
    if shutil.which("cvlc"):
        return ["cvlc"]
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

    if shutil.which("xdotool") is None:
        return

    # Minimize only known terminal windows; never minimize the active window blindly
    # because VLC can be active during playback.
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


def _raise_vlc_windows_linux():
    if not sys.platform.startswith("linux"):
        return
    if shutil.which("xdotool") is None:
        return

    for token_type, token_value in (("--class", "vlc"), ("--name", "VLC media player")):
        try:
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", token_type, token_value],
                capture_output=True,
                text=True,
                check=False,
            )
            window_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
            for window_id in window_ids:
                subprocess.run(["xdotool", "windowraise", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                if shutil.which("wmctrl"):
                    subprocess.run(
                        ["wmctrl", "-i", "-r", window_id, "-b", "add,fullscreen,above"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
        except Exception:
            continue

    # Extra fallback by window title tokens for terminal apps that do not expose expected class.
    for token in ("Terminal", "LXTerminal", "xterm", "bash", "zsh"):
        try:
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", token],
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


def _send_vlc_command(command: str, timeout_seconds: float = 0.8) -> str:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect((VLC_RC_HOST, vlc_rc_port_in_use))
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


def _can_connect_vlc_rc(timeout_seconds: float = 0.6) -> bool:
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(timeout_seconds)
    try:
        client.connect((VLC_RC_HOST, vlc_rc_port_in_use))
        return True
    except Exception:
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def _wait_for_vlc_rc(timeout_seconds: float = 10.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if vlc_controller_process and vlc_controller_process.poll() is not None:
            return False
        # Some VLC builds accept RC connections but return no immediate status text.
        if _can_connect_vlc_rc() or _send_vlc_command("status"):
            return True
        time.sleep(0.1)
    return False


def _quote_path(path_value: str) -> str:
    return '"' + path_value.replace('"', '\\"') + '"'


def _build_vlc_rc_commands(player_cmd, rc_port, initial_media_path):
    common_video_args = [
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-video-deco",
        "--no-qt-fs-controller",
        "--quiet",
        "--no-audio",
    ]

    commands = []
    commands.append(
        player_cmd
        + common_video_args
        + ["--extraintf", "rc", "--rc-host", f"{VLC_RC_HOST}:{rc_port}", initial_media_path]
    )

    base_exec = player_cmd[0]
    commands.append(
        [base_exec, "-I", "rc"]
        + common_video_args
        + ["--rc-host", f"{VLC_RC_HOST}:{rc_port}", initial_media_path]
    )

    commands.append(
        [base_exec, "-I", "rc"]
        + common_video_args
        + ["--rc-host", f"{VLC_RC_HOST}:{rc_port}", "--rc-fake-tty", initial_media_path]
    )

    return commands


def _wait_for_vlc_playing(timeout_seconds: float = 3.0) -> bool:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        state = _send_vlc_command("is_playing", timeout_seconds=0.8).strip().lower()
        if "1" in state:
            return True
        time.sleep(0.1)
    return False


def _start_vlc_controller(initial_media_path: str) -> bool:
    global vlc_controller_process, vlc_rc_port_in_use
    player_cmd = _get_vlc_player_cmd()
    if player_cmd is None:
        logger.error("Neither 'cvlc' nor 'vlc' command is available")
        return False

    vlc_controller_process = _stop_process(vlc_controller_process)

    port_candidates = [VLC_RC_PORT + i for i in range(max(1, VLC_RC_PORT_FALLBACK_COUNT))]

    for rc_port in port_candidates:
        candidate_cmds = _build_vlc_rc_commands(player_cmd, rc_port, initial_media_path)
        for cmd in candidate_cmds:
            logger.info(f"Trying VLC RC startup on {VLC_RC_HOST}:{rc_port} with cmd: {' '.join(cmd)}")
            vlc_controller_process = _stop_process(vlc_controller_process)
            vlc_controller_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            vlc_rc_port_in_use = rc_port
            if _wait_for_vlc_rc():
                # Candidate is considered valid only if playback can actually start.
                _send_vlc_command("stop")
                _send_vlc_command("clear")
                _send_vlc_command(f"add {_quote_path(initial_media_path)}")
                _send_vlc_command("seek 0")
                _send_vlc_command("play")
                _send_vlc_command("fullscreen on")
                if _wait_for_vlc_playing(timeout_seconds=3.5):
                    logger.info(f"VLC RC controller started on {VLC_RC_HOST}:{vlc_rc_port_in_use}")
                    return True

                logger.warning(
                    f"RC connected but playback did not start for cmd: {' '.join(cmd)}"
                )

    vlc_controller_process = _stop_process(vlc_controller_process)
    logger.error("VLC RC startup failed for all command/port candidates")
    return False


def _preload_playlist(video_items):
    if not video_items:
        return

    first_name, first_path = video_items[0]

    # Rebuild playlist explicitly in RC to ensure predictable ordering.
    _send_vlc_command("stop")
    _send_vlc_command("clear")
    _send_vlc_command("repeat off")
    _send_vlc_command("loop on")
    _send_vlc_command("random off")

    _send_vlc_command(f"add {_quote_path(first_path)}")
    time.sleep(0.12)

    for _name, path in video_items[1:]:
        _send_vlc_command(f"enqueue {_quote_path(path)}")
        time.sleep(0.05)

    playlist_text = _send_vlc_command("playlist", timeout_seconds=1.2)
    if playlist_text:
        logger.info("VLC playlist rebuilt successfully")
    else:
        logger.warning("VLC playlist output empty after rebuild")

    _send_vlc_command("seek 0")
    _send_vlc_command("play")
    logger.info(f"Preloaded full playlist; starting from: {first_name}")


def _switch_to_preloaded_index(name: str) -> bool:
    global current_playlist_index
    hide_terminal_window_linux()
    _send_vlc_command("next")
    _send_vlc_command("seek 0")
    _send_vlc_command("play")
    _send_vlc_command("fullscreen on")
    _raise_vlc_windows_linux()
    current_playlist_index += 1
    logger.info(f"Switched to: {name}")
    return True


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
        use_rc = _start_vlc_controller(resolved_sequence[0][1])
        if not use_rc:
            logger.error("Could not start VLC RC controller")
            return

        _preload_playlist(resolved_sequence)
        logger.info("Preloaded all videos at startup")

        first_name, _first_path = resolved_sequence[0]
        _send_vlc_command("seek 0")
        _send_vlc_command("play")
        _send_vlc_command("fullscreen on")
        _raise_vlc_windows_linux()
        logger.info(f"Started initial video: {first_name}")

        index = 1

        while True:
            name, _path = resolved_sequence[index % len(resolved_sequence)]
            switched = _switch_to_preloaded_index(name)
            if not switched:
                logger.warning("Switch failed; keeping current preloaded VLC session active")
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
