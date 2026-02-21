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
# X11 ENV — ABSOLUTELY REQUIRED
# ===============================
os.environ["DISPLAY"] = ":0"

home = os.path.expanduser("~")
xauth = os.path.join(home, ".Xauthority")
if os.path.exists(xauth):
    os.environ["XAUTHORITY"] = xauth
else:
    log.error("Missing .Xauthority — VLC cannot open X window")
    sys.exit(1)

os.environ["XDG_SESSION_TYPE"] = "x11"
os.environ["QT_QPA_PLATFORM"] = "xcb"

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

SWITCH_INTERVAL = 5
RC_HOST = "127.0.0.1"
RC_PORT = 4215

# ===============================
# VLC RC HELPERS
# ===============================
def rc(cmd):
    try:
        s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.4)
        s.sendall((cmd + "\n").encode())
        s.close()
    except Exception:
        pass


def wait_for_rc(timeout=6):
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
# START VLC (SINGLE WINDOW)
# ===============================
def start_vlc(first_video):
    if not shutil.which("cvlc"):
        log.error("cvlc not installed")
        sys.exit(1)

    cmd = [
        "cvlc",
        "--intf", "dummy",
        "--extraintf", "rc",
        "--rc-host", f"{RC_HOST}:{RC_PORT}",

        "--vout", "x11",
        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-osd",
        "--no-audio",

        first_video,
    ]

    log.info("Launching VLC:")
    log.info(" ".join(cmd))

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=os.environ.copy(),
    )

    if not wait_for_rc():
        err = proc.stderr.read().decode(errors="ignore")
        log.error("VLC failed to start RC interface")
        log.error(err)
        proc.terminate()
        sys.exit(1)

    log.info("VLC RC connected successfully")


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
        log.error("No videos found — exiting")
        return

    start_vlc(video_paths[0])

    rc("stop")
    rc("clear")
    rc("loop on")
    rc("random off")

    for v in video_paths:
        rc(f"enqueue {v}")

    rc("seek 0")
    rc("play")
    rc("fullscreen on")

    log.info("Playback started")

    while True:
        time.sleep(SWITCH_INTERVAL)
        rc("next")
        rc("seek 0")
        rc("play")
        rc("fullscreen on")
        log.info("Switched video")


if __name__ == "__main__":
    main()