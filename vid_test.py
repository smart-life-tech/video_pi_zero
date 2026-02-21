#!/usr/bin/env python3
import os
import time
import subprocess
import socket
import shutil
import sys

# ---------- ENV FIX FOR PI ----------
os.environ.setdefault("DISPLAY", ":0")
os.environ.setdefault("XDG_SESSION_TYPE", "x11")
os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

# ---------- CONFIG ----------
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

# ---------- VLC RC HELPERS ----------
def rc(cmd):
    try:
        s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.5)
        s.sendall((cmd + "\n").encode())
        s.close()
    except Exception:
        pass

def wait_rc(timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        try:
            s = socket.create_connection((RC_HOST, RC_PORT), timeout=0.3)
            s.close()
            return True
        except Exception:
            time.sleep(0.1)
    return False

# ---------- START VLC ----------
def start_vlc(first_video):
    if not shutil.which("vlc"):
        print("VLC not installed")
        sys.exit(1)

    cmd = [
        "vlc",
        "--fullscreen",
        "--no-video-title-show",
        "--no-qt-fs-controller",
        "--quiet",
        "--no-audio",
        "--extraintf", "rc",
        "--rc-host", f"{RC_HOST}:{RC_PORT}",
        first_video,
    ]

    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    if not wait_rc():
        print("VLC RC failed")
        sys.exit(1)

# ---------- MAIN ----------
def main():
    video_paths = [os.path.abspath(v) for v in VIDEOS if os.path.exists(v)]
    if not video_paths:
        print("No videos found")
        return

    start_vlc(video_paths[0])

    # Build playlist
    rc("stop")
    rc("clear")
    for v in video_paths:
        rc(f"enqueue {v}")

    rc("loop on")
    rc("seek 0")
    rc("play")
    rc("fullscreen on")

    index = 0
    while True:
        rc("next")
        rc("seek 0")
        rc("play")
        rc("fullscreen on")
        index += 1
        time.sleep(SWITCH_INTERVAL)

if __name__ == "__main__":
    main()