# Raspberry Pi Video Player

A GPIO-controlled video player for Raspberry Pi Zero that plays videos based on button presses.

## Features

- **GPIO Button Controls**: Four buttons (GPIO pins 17, 27, 22, 4) trigger different video playback
- **Fullscreen Playback**: Videos play in fullscreen mode using VLC
- **Seamless Transitions**: Smooth video switching without display glitches

## Hardware Requirements

- Raspberry Pi Zero
- 4 buttons connected to GPIO pins:
  - Pin 17: Plays Process.mp4
  - Pin 27: Plays Place.mp4
  - Pin 22: Plays Warning.mp4
  - Pin 4: Stops playback

## Software Dependencies

```bash
pip install gpiozero python-vlc
```

## Usage

### On Raspberry Pi (GPIO)

Run the script:
```bash
python sendto\ fiv.py
```

The program will wait for button presses and play the corresponding videos from `/home/helmwash/Videos/`.

### On Windows (Keyboard Test Mode)

Place your test videos as any of:
- `./Videos/Process.mp4`, `./Videos/Place.mp4`, `./Videos/Warning.mp4`
- Or any accessible absolute/relative path and update filenames if needed

Run the script:
```bash
python "sendto fiv.py"
```

Controls in the console:
- `A`: Play Process.mp4
- `B`: Play Place.mp4
- `C`: Play Warning.mp4
- `D`: Stop playback
- `Q`: Quit program

## Button Map

| GPIO Pin | Action | Video |
|----------|--------|-------|
| 17 | Start | Process.mp4 |
| 27 | Start | Place.mp4 |
| 22 | Start | Warning.mp4 |
| 4 | Stop | N/A |

## Video Paths

The app resolves paths in this order:
1) As provided (relative/absolute)
2) `./Videos/<filename>` (relative to current working directory)
3) `/home/helmwash/Videos/<filename>` (Pi default)

Default filenames used:
- `button_pressed_17()`: Process.mp4
- `button_pressed_27()`: Place.mp4
- `button_pressed_22()`: Warning.mp4

## Notes

- Videos must be placed in `/home/helmwash/Videos/`
- The program runs indefinitely until interrupted (Ctrl+C)
- Seamless transitions are achieved by preparing the next video before stopping the current one

## Flask Dual-Slot PLC Control

This project now includes a web dashboard for two helmet-wash slots with:

- Split-screen live video panels
- On-screen Start and Stop overlay buttons for each slot
- PLC command write via Modbus TCP when buttons are pressed
- Live running/idle status polling from PLC coils

### Files

- `flask_dual_control.py`: Flask backend + Modbus read/write API
- `templates/dual_control.html`: UI layout
- `static/dual_control.css`: split-screen styling and overlay controls
- `static/dual_control.js`: button actions and status polling

### Install

```bash
pip install -r requirements.txt
```

### Run

```bash
python flask_dual_control.py
```

Open:

```text
http://<pi-ip>:8080
```

### Environment Variables

Use these to match your PLC address and coil mapping:

- `MODBUS_SERVER_IP` (default `192.168.1.100`)
- `MODBUS_SERVER_PORT` (default `504`)
- `MODBUS_UNIT_ID` (default `1`)
- `SLOT1_START_COIL` (default `10`)
- `SLOT1_STOP_COIL` (default `11`)
- `SLOT1_RUNNING_COIL` (default `20`)
- `SLOT2_START_COIL` (default `12`)
- `SLOT2_STOP_COIL` (default `13`)
- `SLOT2_RUNNING_COIL` (default `21`)
- `SLOT1_VIDEO` (default `Guide_steps.mp4`)
- `SLOT2_VIDEO` (default `Process_step_3.mp4`)

Example:

```bash
MODBUS_SERVER_IP=192.168.1.100 SLOT1_START_COIL=0 SLOT1_STOP_COIL=5 python flask_dual_control.py
```

### API Endpoints

- `POST /api/slot/slot1/start`
- `POST /api/slot/slot1/stop`
- `POST /api/slot/slot2/start`
- `POST /api/slot/slot2/stop`
- `GET /api/status`
- `GET /api/health`
