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
TRANSITION_BLACK_HOLD_SECONDS = float(os.environ.get("VID_TEST_BLACK_HOLD_SECONDS", "0.65"))
TERMINAL_GUARD_INTERVAL_SECONDS = float(os.environ.get("VID_TEST_TERMINAL_GUARD_SECONDS", "0.1"))
STARTUP_BLACK_HOLD_SECONDS = float(os.environ.get("VID_TEST_STARTUP_BLACK_HOLD_SECONDS", "1.5"))

video_process_lock = threading.Lock()
current_video_process = None
black_vlc_process = None
terminal_guard_running = False
BLACK_IMAGE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_black_test.ppm")


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


def _vlc_fullscreen_base_args():
    return [
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-video-deco",
        "--no-qt-fs-controller",
        "--quiet",
    ]


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


def _raise_vlc_windows_for_pid_linux(process_handle):
    if not sys.platform.startswith("linux") or process_handle is None:
        return
    if shutil.which("xdotool") is None:
        return

    try:
        result = subprocess.run(
            ["xdotool", "search", "--pid", str(process_handle.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        window_ids = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        for window_id in window_ids:
            if shutil.which("wmctrl"):
                subprocess.run(
                    ["wmctrl", "-i", "-r", window_id, "-b", "add,fullscreen,above"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            subprocess.run(["xdotool", "windowraise", window_id], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except Exception:
        return


def _post_launch_fix_vlc_window(process_handle, delay_seconds=0.0):
    if not sys.platform.startswith("linux"):
        return

    def _delayed_fix():
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        _raise_vlc_windows_for_pid_linux(process_handle)

    threading.Thread(target=_delayed_fix, daemon=True).start()


def _hold_black_cover_on_top_linux(black_process_handle, hold_seconds=0.45):
    if not sys.platform.startswith("linux"):
        return
    if black_process_handle is None:
        return

    deadline = time.time() + max(0.0, hold_seconds)
    while time.time() < deadline:
        try:
            if black_process_handle.poll() is not None:
                return
            _raise_vlc_windows_for_pid_linux(black_process_handle)
        except Exception:
            return
        time.sleep(0.05)


def hide_terminal_window_linux():
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
                return
        except Exception:
            continue


def terminal_guard_loop():
    global terminal_guard_running
    if not sys.platform.startswith("linux"):
        return
    while terminal_guard_running:
        hide_terminal_window_linux()
        time.sleep(TERMINAL_GUARD_INTERVAL_SECONDS)


def _ensure_black_image_file():
    if os.path.exists(BLACK_IMAGE_PATH):
        return
    with open(BLACK_IMAGE_PATH, "w", encoding="ascii") as file:
        file.write("P3\n1 1\n255\n0 0 0\n")


def _ensure_black_screen_loop_locked():
    global black_vlc_process

    if black_vlc_process is not None and black_vlc_process.poll() is None:
        return

    player_cmd = _get_vlc_player_cmd()
    if player_cmd is None:
        raise RuntimeError("Neither 'cvlc' nor 'vlc' command is available")

    _ensure_black_image_file()
    black_vlc_process = _stop_process(black_vlc_process)

    cmd = player_cmd + _vlc_fullscreen_base_args() + [
        "--loop",
        "--image-duration", "-1",
        "--no-audio",
        BLACK_IMAGE_PATH,
    ]
    black_vlc_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _post_launch_fix_vlc_window(black_vlc_process)


def _prepare_transition_cover_locked():
    hide_terminal_window_linux()
    _ensure_black_screen_loop_locked()
    if black_vlc_process is not None and black_vlc_process.poll() is None:
        _raise_vlc_windows_for_pid_linux(black_vlc_process)
    time.sleep(0.08)


def play_video_smooth(video_file: str):
    global current_video_process

    video_path = resolve_video_path(video_file)
    if not os.path.exists(video_path):
        logger.warning(f"Missing video, skipped: {video_path}")
        return

    player_cmd = _get_vlc_player_cmd()
    if player_cmd is None:
        logger.error("Install VLC command-line player (cvlc)")
        return

    with video_process_lock:
        _prepare_transition_cover_locked()

        current_video_process = _stop_process(current_video_process)

        if black_vlc_process is not None and black_vlc_process.poll() is None:
            threading.Thread(
                target=_hold_black_cover_on_top_linux,
                args=(black_vlc_process, TRANSITION_BLACK_HOLD_SECONDS),
                daemon=True,
            ).start()

        cmd = player_cmd + _vlc_fullscreen_base_args() + [
            "--play-and-exit",
            "--no-audio",
            video_path,
        ]
        current_video_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _post_launch_fix_vlc_window(current_video_process, delay_seconds=TRANSITION_BLACK_HOLD_SECONDS)

    logger.info(f"Now playing: {video_file}")


def main():
    global terminal_guard_running, current_video_process, black_vlc_process

    logger.info("=== Timed Video Test Started ===")
    logger.info(f"Switch interval: {SWITCH_INTERVAL_SECONDS}s")
    logger.info(f"Sequence: {VIDEO_SEQUENCE}")

    if not sys.platform.startswith("linux"):
        logger.error("vid_test.py is intended for Raspberry Pi/Linux external VLC mode.")
        return

    terminal_guard_running = True
    terminal_guard_thread = threading.Thread(target=terminal_guard_loop, daemon=True)
    terminal_guard_thread.start()

    try:
        with video_process_lock:
            _ensure_black_screen_loop_locked()
            if black_vlc_process is not None and black_vlc_process.poll() is None:
                _hold_black_cover_on_top_linux(black_vlc_process, STARTUP_BLACK_HOLD_SECONDS)

        index = 0
        while True:
            video_file = VIDEO_SEQUENCE[index % len(VIDEO_SEQUENCE)]
            play_video_smooth(video_file)
            index += 1

            sleep_left = SWITCH_INTERVAL_SECONDS
            while sleep_left > 0:
                tick = min(0.2, sleep_left)
                time.sleep(tick)
                sleep_left -= tick

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        terminal_guard_running = False
        try:
            terminal_guard_thread.join(timeout=1)
        except Exception:
            pass

        with video_process_lock:
            current_video_process = _stop_process(current_video_process)
            black_vlc_process = _stop_process(black_vlc_process)

        logger.info("vid_test shutdown complete")


if __name__ == "__main__":
    main()
