# export XDG_SESSION_TYPE=x11
# export QT_QPA_PLATFORM=xcb
# python vid_modbus.py

import os
import sys
import time
import threading
import logging

# Setup logging to file and console
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_modbus.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.info("Modbus Video Player started")

# Import Modbus TCP Client
try:
    from pymodbus.client import ModbusTcpClient
    HAS_MODBUS = True
except ImportError:
    logger.error("pymodbus not installed! Install with: pip install pymodbus")
    HAS_MODBUS = False

# Tkinter for GUI
try:
    import tkinter as tk
except ImportError:
    tk = None

# Import VLC setup from original vid.py
import importlib.util
spec = importlib.util.spec_from_file_location("vid_original", os.path.join(os.path.dirname(__file__), "vid.py"))
if spec and spec.loader:
    vid_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vid_module)
    _setup_vlc_windows = vid_module._setup_vlc_windows
    locate_videos_folder = vid_module.locate_videos_folder
    play_video = vid_module.play_video
    init_video_window = vid_module.init_video_window
else:
    # Fallback - you may need to copy these functions here
    logger.error("Could not import from vid.py - copy necessary functions manually")
    sys.exit(1)

# =============================================================================
# MODBUS CONFIGURATION
# =============================================================================
MODBUS_SERVER_IP = "192.168.1.100"  # Change to your Siemens LOGO! 8 IP address
MODBUS_SERVER_PORT = 502  # Standard Modbus TCP port
MODBUS_UNIT_ID = 1  # Modbus slave/unit ID (typically 1 for LOGO!)

# Modbus coil addresses for video triggers (0-based addressing)
# These map to your 5 GPIO buttons
MODBUS_COILS = {
    "Process_step_1": 0,    # Was GPIO 17
    "Guide_steps": 1,       # Was GPIO 27
    "Warning": 2,           # Was GPIO 22
    "Process_step_2": 3,    # Was GPIO 4
    "Process_step_3": 4,    # Was GPIO 18
}

# Video file mappings
VIDEO_FILES = {
    "Process_step_1": "Process_step_1.mp4",
    "Guide_steps": "Guide_steps.mp4",
    "Warning": "Warning.mp4",
    "Process_step_2": "Process_step_2.mp4",
    "Process_step_3": "Process_step_3.mp4",
}

# Debounce settings
last_trigger_time = {}
for key in MODBUS_COILS.keys():
    last_trigger_time[key] = 0
COOLDOWN_SECONDS = 5  # Minimum seconds between triggers

# Global Modbus client
modbus_client = None

# =============================================================================
# MODBUS FUNCTIONS
# =============================================================================

def connect_modbus():
    """Connect to the Siemens LOGO! 8 PLC via Modbus TCP"""
    global modbus_client
    try:
        logger.info(f"Connecting to Modbus server at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
        modbus_client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT)
        
        if modbus_client.connect():
            logger.info("Successfully connected to Modbus server")
            return True
        else:
            logger.error("Failed to connect to Modbus server")
            return False
    except Exception as e:
        logger.error(f"Modbus connection error: {e}")
        return False


def read_modbus_coils():
    """Read all configured coils from the PLC and return their states"""
    if not modbus_client or not modbus_client.is_socket_open():
        logger.warning("Modbus client not connected")
        return None
    
    try:
        # Read 5 coils starting from address 0
        result = modbus_client.read_coils(0, 5)
        
        if result.isError():
            logger.error(f"Error reading coils: {result}")
            return None
        
        return result.bits[:5]  # Return first 5 coil states
    
    except Exception as e:
        logger.error(f"Exception reading Modbus coils: {e}")
        return None


def can_trigger_action(action_name):
    """Check if enough time has passed since last trigger (debounce)"""
    current_time = time.time()
    time_since_last = current_time - last_trigger_time[action_name]
    
    if time_since_last < COOLDOWN_SECONDS:
        return False
    
    last_trigger_time[action_name] = current_time
    return True


def handle_modbus_trigger(action_name):
    """Handle a Modbus trigger by playing the appropriate video"""
    if can_trigger_action(action_name):
        video_file = VIDEO_FILES[action_name]
        logger.info(f"Modbus trigger: {action_name} -> {video_file}")
        print(f"Playing {video_file} triggered by {action_name}")
        play_video(video_file)


def modbus_polling_loop():
    """Main loop that polls Modbus coils and triggers videos"""
    logger.info("Starting Modbus polling loop")
    
    # Track last state of each coil to detect rising edge (0 -> 1 transition)
    last_coil_states = [False] * 5
    
    poll_interval = 0.1  # Poll every 100ms
    
    while True:
        try:
            # Read current coil states
            coil_states = read_modbus_coils()
            
            if coil_states is None:
                # Connection lost, try to reconnect
                logger.warning("Lost Modbus connection, attempting to reconnect...")
                time.sleep(2)
                if not connect_modbus():
                    time.sleep(3)
                    continue
                else:
                    # Reset last states after reconnection
                    last_coil_states = [False] * 5
                    continue
            
            # Check each coil for rising edge (transition from False to True)
            for idx, (action_name, coil_addr) in enumerate(MODBUS_COILS.items()):
                current_state = coil_states[idx]
                previous_state = last_coil_states[idx]
                
                # Trigger on rising edge (0 -> 1)
                if current_state and not previous_state:
                    logger.info(f"Rising edge detected on coil {coil_addr} ({action_name})")
                    handle_modbus_trigger(action_name)
                
                # Update last state
                last_coil_states[idx] = current_state
            
            time.sleep(poll_interval)
            
        except KeyboardInterrupt:
            logger.info("Modbus polling interrupted by user")
            break
        except Exception as e:
            logger.error(f"Error in Modbus polling loop: {e}")
            time.sleep(1)
    
    # Cleanup
    if modbus_client:
        modbus_client.close()
        logger.info("Modbus connection closed")


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def main():
    logger.info("=== Modbus Video Player Startup ===")
    logger.info(f"Modbus Server: {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
    logger.info(f"Configured coils: {MODBUS_COILS}")
    
    if not HAS_MODBUS:
        logger.error("Cannot run without pymodbus. Install it with: pip install pymodbus")
        print("\nERROR: pymodbus not installed!")
        print("Install it with: pip install pymodbus")
        return
    
    # Connect to Modbus server
    if not connect_modbus():
        logger.error("Failed to establish initial Modbus connection")
        print(f"\nERROR: Could not connect to Modbus server at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
        print("Please check:")
        print("1. PLC is powered on")
        print("2. Network connection is working")
        print("3. IP address is correct in the script")
        print("4. Modbus TCP is enabled on the LOGO! 8")
        return
    
    # Auto-play first video on startup
    logger.info("Auto-playing first video...")
    play_video("Guide_steps.mp4")
    
    # Create GUI window (black fullscreen on Pi, embedded on Windows)
    root = init_video_window()
    
    # Start Modbus polling in background thread
    modbus_thread = threading.Thread(target=modbus_polling_loop, daemon=True)
    modbus_thread.start()
    logger.info("Modbus polling thread started")
    
    # Run GUI main loop (if available)
    if root is not None:
        logger.info("Starting GUI main loop")
        print("\nModbus Video Player running...")
        print(f"Monitoring Modbus coils at {MODBUS_SERVER_IP}")
        print("Waiting for PLC triggers...\n")
        try:
            root.mainloop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    else:
        # No GUI - just wait for Modbus triggers
        logger.info("Running without GUI (console mode)")
        print("\nModbus Video Player running in console mode...")
        print(f"Monitoring Modbus coils at {MODBUS_SERVER_IP}")
        print("Press Ctrl+C to exit\n")
        try:
            modbus_thread.join()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    
    # Cleanup
    if modbus_client:
        modbus_client.close()
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
