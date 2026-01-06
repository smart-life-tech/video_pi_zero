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

Run the script:
```bash
python sendto_fiv.py
```

The program will wait for button presses and play the corresponding videos from `/home/helmwash/Videos/`.

## Button Map

| GPIO Pin | Action | Video |
|----------|--------|-------|
| 17 | Start | Process.mp4 |
| 27 | Start | Place.mp4 |
| 22 | Start | Warning.mp4 |
| 4 | Stop | N/A |

## Video Paths

Update the video paths in the button handler functions as needed:
- `button_pressed_17()`: Process.mp4
- `button_pressed_27()`: Place.mp4
- `button_pressed_22()`: Warning.mp4

## Notes

- Videos must be placed in `/home/helmwash/Videos/`
- The program runs indefinitely until interrupted (Ctrl+C)
- Seamless transitions are achieved by preparing the next video before stopping the current one
