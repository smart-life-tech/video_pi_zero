Language support upgrade for vid_modbus.py

Overview
--------
This project adds a simple language selection flow (English / Spanish) to the existing vid_modbus.py playback + Modbus trigger system.

At startup the user is presented a fullscreen language selector (Tkinter) running on X11. The selected language determines which video files are loaded and played for the guide and triggered steps. After the final step is reached, the app returns to the language selector.

Spanish filenames
-----------------
The code expects Spanish video files to use the exact filenames below (place them in the same directory as vid_modbus.py or in the Videos/ subfolder):

- Guide_steps_spanish.mp4
- process_step1_spanish.mp4
- process_step2_spanish.mp4
- process_step3_spanish.mp4
- warning_spanish.mp4

If your files use different names, either rename them to match the list above or update `load_video_files_for_language()` in `vid_modbus.py` to point to your filenames.

How it works
------------
- On startup the app calls `show_language_selector()` which displays a simple fullscreen chooser (English / Español) using Tkinter.
- The selection sets `LANGUAGE` and `VIDEO_FILES` mapping.
- The playlist is built from the resolved video files and VLC (cvlc) is started with the RC interface.
- Modbus coils 0-4 trigger rising-edge playback of the mapped videos. The trigger mapping is unchanged — only the filenames change depending on language.
- When the final step (`Process_step_3`) is triggered, the app will briefly pause then return to the language selector, and reload the playlist for the newly selected language.

Files changed
-------------
- vid_modbus.py — language selector (Tkinter), language-aware video mapping, Spanish filename mapping, language-agnostic switching logic.
- README_L10N.md — this file.

Running
-------
Prerequisites:
- Linux/X11 session (DISPLAY set, XAUTHORITY accessible)
- Python 3.8+
- cvlc (VLC) installed
- tkinter available in Python
- pymodbus installed

Install dependencies (Debian/Ubuntu example):

```bash
sudo apt update
sudo apt install -y vlc python3-tk
pip3 install pymodbus
```

Run the application:

```bash
python3 vid_modbus.py
```

Behavior on first run:
- You will see a fullscreen language selection dialog. Choose `English` or `Español`.
- The app will build a language-specific playlist and play the guide video.
- PLC/Modbus triggers will play language-appropriate videos.

Environment variables
---------------------
The existing environment variables for Modbus and VLC remain supported; important ones include:
- `MODBUS_SERVER_IP` (default: 192.168.1.100)
- `MODBUS_SERVER_PORT` (default: 504)
- `VLC_RC_PORT` (default: 4213)
- `VLC_LOG_FILE` (default: vlc_startup.log)
- `VLC_VOLUME_PERCENT` (0-200, default: 80)

Troubleshooting
---------------
- "No usable .Xauthority found": ensure the script runs in a user session that has an X11 display. When run as sudo, the script attempts to detect the invoking user's Xauthority.
- "Tkinter not available": install the system package (`python3-tk` on Debian/Ubuntu) or remove the selector by editing `show_language_selector()`.
- Missing Spanish videos: put the Spanish MP4 files in the project directory or Videos/ subfolder, matching the filenames listed above.
- VLC RC not responding: check that `cvlc` is available and that nothing else is using the RC port.

Customization
-------------
- To change Spanish filenames: update `load_video_files_for_language()` mapping in `vid_modbus.py`.
- To change language UI (e.g., add more languages), modify `show_language_selector()` and add new mappings in `load_video_files_for_language()`.

If you'd like, I can:
- Add a small script to verify video filenames are present and list missing files.
- Make the selector non-blocking and running as an overlay while Modbus monitoring continues.
- Add translations for the selector UI text.
