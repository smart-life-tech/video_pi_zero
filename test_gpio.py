#!/usr/bin/env python3
"""GPIO Test Script - Check if all buttons are working"""

import time
from gpiozero import Button

print("GPIO Button Test")
print("Press each button and watch for output...")
print("Press Ctrl+C to exit\n")

# Define buttons
buttons = {
    4: Button(4),
    17: Button(17),
    18: Button(18),
    22: Button(22),
    27: Button(27)
}

# Setup callbacks
def make_callback(pin):
    def callback():
        print(f"✓ GPIO {pin} PRESSED!")
    return callback

for pin, btn in buttons.items():
    btn.when_pressed = make_callback(pin)
    print(f"Monitoring GPIO {pin}...")

print("\nWaiting for button presses...\n")

try:
    while True:
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nTest stopped.")
