#!/usr/bin/env python3
import os
import time
import socket
import subprocess
import shutil
import sys

# ===============================
# X11 ENV (CRITICAL ON PI)
# ===============================
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("XDG_SESSION_TYPE", "x11")
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

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
# START VLC (SINGLE WINDOW)
# ===============================
def start_vlc(first_video: str):
    if not shutil.which("cvlc"):
        print("ERROR: cvlc not installed")
        sys.exit(1)

    cmd = [
        "cvlc",
        "--intf", "dummy",                 # NO Qt window
        "--extraintf", "rc",
        "--rc-host", f"{RC_HOST}:{RC_PORT}",

        "--fullscreen",
        "--video-on-top",
        "--no-video-title-show",
        "--no-osd",
        "--no-snapshot-preview",

        "--vout", "x11",                   # Force single X11 window
        "--no-audio",

        "--mouse-hide-timeout=0",
        "--no-keyboard-events",
        "--no-mouse-events",

        first_video,
    ]

    subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    if not wait_for_rc():
        print("ERROR: VLC RC interface not responding")
        sys.exit(1)


# ===============================
# MAIN
# ===============================
def main():
    # Resolve absolute paths
    video_paths = []
    for v in VIDEOS:
        path = os.path.abspath(v)
        if os.path.exists(path):
            video_paths.append(path)
        else:
            print(f"WARNING: missing video: {path}")

    if not video_paths:
        print("ERROR: No valid videos found")
        return

    # Start VLC
    start_vlc(video_paths[0])

    # Build playlist
    rc("stop")
    rc("clear")
    rc("loop on")
    rc("random off")

    for v in video_paths:
        rc(f"enqueue {v}")

    rc("seek 0")
    rc("play")
    rc("fullscreen on")

    # Switch loop
    while True:
        time.sleep(SWITCH_INTERVAL_SECONDS)
        rc("next")
        rc("seek 0")
        rc("play")
        rc("fullscreen on")


if __name__ == "__main__":
    main()