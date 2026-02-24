# Audio Volume Settings (Raspberry Pi)

This guide explains how to control audio output and volume for `vid_modbus.py`, especially when using an external speaker.

## 1) Install required audio tools

```bash
sudo apt update
sudo apt install -y alsa-utils pulseaudio-utils pipewire-bin vlc
```

## 2) Find available output sinks (external speaker vs HDMI)

```bash
pactl list short sinks
```

Example output:
- `57 alsa_output.usb-...` = USB external speaker
- `58 alsa_output.platform-...hdmi...` = HDMI monitor audio

## 3) Select your external speaker as default

Use the sink ID or sink name from step 2.

```bash
pactl set-default-sink 57
pactl set-sink-mute 57 0
pactl set-sink-volume 57 80%
```

## 4) Run the player with explicit volume/backend

```bash
VLC_AOUT=pulse VLC_VOLUME_PERCENT=80 python3 vid_modbus.py
```

If you run with sudo:

```bash
sudo -E env VLC_AOUT=pulse VLC_VOLUME_PERCENT=80 python3 vid_modbus.py
```

## 5) Lower or raise volume while running

```bash
pactl set-sink-volume 57 40%   # lower
pactl set-sink-volume 57 120%  # raise
```

Tip: typical range is `20%` to `120%`.

## 6) Useful environment variables in `vid_modbus.py`

- `VLC_VOLUME_PERCENT` (default `100`)
  - Startup volume used by VLC and system mixer helpers.
- `VLC_AOUT`
  - Optional VLC audio backend override (`pulse` or `alsa`).
- `VLC_ALSA_DEVICE` (default `default`)
  - ALSA device name when using `VLC_AOUT=alsa`.

Examples:

```bash
VLC_AOUT=pulse VLC_VOLUME_PERCENT=50 python3 vid_modbus.py
VLC_AOUT=alsa VLC_ALSA_DEVICE=default VLC_VOLUME_PERCENT=70 python3 vid_modbus.py
```

## 7) Troubleshooting

### Sound at startup but silent after video switch
- Keep using `VLC_AOUT=pulse`.
- Confirm the default sink is your external speaker:

```bash
pactl get-default-sink
```

- Re-apply sink volume:

```bash
pactl set-sink-mute @DEFAULT_SINK@ 0
pactl set-sink-volume @DEFAULT_SINK@ 80%
```

### `No ALSA mixer controls found`
This is OK if PipeWire/PulseAudio is active. Use `pactl`/`wpctl` sink control instead of `amixer`.

### 3.5mm jack speaker on Raspberry Pi
If needed, force analog output:

```bash
sudo raspi-config
```

Then go to:
- `System Options` -> `Audio` -> `Headphones`

## 8) Quick one-line startup (external speaker)

```bash
pactl set-default-sink 57; pactl set-sink-mute 57 0; pactl set-sink-volume 57 80%; VLC_AOUT=pulse VLC_VOLUME_PERCENT=80 python3 vid_modbus.py
```
