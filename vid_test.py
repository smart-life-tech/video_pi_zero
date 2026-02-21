#!/usr/bin/env python3
import os
import time
import socket
import subprocess
import shutil
import sys
import logging

# ===============================
# LOGGING
# ===============================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("vid_test.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("vid_test")

# ===============================
# X11 ENV (MANDATORY)
# ===============================
os.environ["DISPLAY"] = ":0"
os.environ["XDG_SESSION_TYPE"] = "x11"
os.environ["QT_QPA_PLATFORM"] = "xcb"

home = os.path.expanduser("~")
xauth = os.path.join(home, ".Xauthority")
if not os.path.exists(xauth):
    log.error("Missing ~/.Xauthority – cannot access X11")
    sys.exit(1)

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

SWITCH_INTERVAL_SECONDS = 5
RC_HOST = "127.0.0.1"
RC_PORT = 4215

# ===============================
# VLC RC HELPERS
# ===============================
def rc(cmd: str):
    try:
        s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.5)
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


# ===============================
# START VLC (WITH DUMMY MEDIA)
# ===============================
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
        "--avcodec-hw=none",      # CRITICAL: disable broken HW decode
        "--video-x", "0",
        "--video-y", "0",

        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-osd",
        "--no-audio",

        dummy_video,              # CRITICAL: forces video window creation
    ]

    log.info("Launching VLC:")
    log.info(" ".join(cmd))

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

    log.info("VLC RC connected")


# ===============================
# MAIN
# ===============================
def main():
    log.info("Starting video switcher")

    video_paths = []
    for v in VIDEOS:
        p = os.path.abspath(v)
        if os.path.exists(p):
            video_paths.append(p)
        else:
            log.warning(f"Missing video: {p}")

    if not video_paths:
        log.error("No valid videos found")
        return

    # Start VLC with first video (dummy)
    start_vlc(video_paths[0])

    # Build playlist cleanly
    rc("stop")
    rc("clear")
    rc("loop off")
    rc("random off")

    for v in video_paths:
        rc(f"add {v}")
        time.sleep(0.05)

    # IMPORTANT: VLC playlist indices are 1-based
    current_index = 1

    rc(f"goto {current_index}")
    rc("seek 0")
    rc("play")
    rc("fullscreen on")

    log.info(f"Playing playlist index {current_index}")

    # Timed switching
    while True:
        time.sleep(SWITCH_INTERVAL_SECONDS)

        current_index += 1
        if current_index > len(video_paths):
            current_index = 1

        rc(f"goto {current_index}")
        rc("seek 0")
        rc("play")
        rc("fullscreen on")

        log.info(f"Switched to playlist index {current_index}")


if __name__ == "__main__":
    main()