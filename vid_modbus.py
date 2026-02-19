# export XDG_SESSION_TYPE=x11
# export QT_QPA_PLATFORM=xcb
# python vid_modbus.py

import os
import sys
import time
import threading
import logging
import subprocess
import queue
import shutil

# Improve VLC stability on Raspberry Pi/Wayland by preferring X11-compatible backend.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")
    os.environ.setdefault("XDG_SESSION_TYPE", "x11")

# Setup logging to file and console
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "debug_modbus.log")
logging.basicConfig(
    level=logging.INFO,  # Changed from DEBUG to reduce console spam
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Silence pymodbus debug logging in console (still logs to file)
logging.getLogger('pymodbus').setLevel(logging.WARNING)

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

def resolve_video_path(filename: str) -> str:
    """Resolve video path for both Pi and Windows runtime."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        filename,
        os.path.join(script_dir, filename),
        os.path.join(os.getcwd(), "Videos", filename),
        os.path.join("/home/helmwash/video_pi_zero", filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return filename


if sys.platform.startswith("linux"):
    # On Pi/Linux, avoid importing vid.py to prevent in-process libVLC segfaults.
    def init_video_window():
        return None

    def play_video(_):
        return None
else:
    # Import VLC setup from original vid.py (Windows path)
    import importlib.util
    spec = importlib.util.spec_from_file_location("vid_original", os.path.join(os.path.dirname(__file__), "vid.py"))
    if spec and spec.loader:
        vid_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(vid_module)
        _setup_vlc_windows = vid_module._setup_vlc_windows
        play_video = vid_module.play_video
        init_video_window = vid_module.init_video_window
    else:
        logger.error("Could not import from vid.py - copy necessary functions manually")
        sys.exit(1)

# =============================================================================
# MODBUS CONFIGURATION
# =============================================================================
MODBUS_SERVER_IP = "192.168.1.100"  # Change to your Siemens LOGO! 8 IP address
MODBUS_SERVER_PORT = 504  # Standard Modbus TCP port
MODBUS_UNIT_ID = 1  # Modbus slave/unit ID (typically 1 for LOGO!)
PI_ETH_INTERFACE = "eth0"
PI_IP = "192.168.1.10"
PI_IP_CIDR = f"{PI_IP}/24"

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

# Video playback queue (serialize requests from Modbus thread)
video_queue = queue.Queue(maxsize=20)
video_process_lock = threading.Lock()
current_vlc_process = None
USE_EXTERNAL_VLC = sys.platform.startswith("linux")


def _stop_external_vlc_locked():
    """Stop existing external VLC process. Caller must hold video_process_lock."""
    global current_vlc_process
    if current_vlc_process is None:
        return
    try:
        if current_vlc_process.poll() is None:
            current_vlc_process.terminate()
            try:
                current_vlc_process.wait(timeout=1.5)
            except subprocess.TimeoutExpired:
                current_vlc_process.kill()
                current_vlc_process.wait(timeout=1.0)
    except Exception as e:
        logger.warning(f"Error stopping external VLC process: {e}")
    finally:
        current_vlc_process = None


def play_video_safe(video_file):
    """Play video robustly; Linux uses external VLC process to avoid libVLC segfaults."""
    global current_vlc_process

    if not USE_EXTERNAL_VLC:
        play_video(video_file)
        return

    video_path = resolve_video_path(video_file)
    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        print(f"Error: Video file not found: {video_path}")
        return

    player_cmd = None
    if shutil.which("cvlc"):
        player_cmd = ["cvlc"]
    elif shutil.which("vlc"):
        player_cmd = ["vlc", "--intf", "dummy"]

    if player_cmd is None:
        logger.error("Neither 'cvlc' nor 'vlc' command is available")
        print("Error: Install VLC command-line player (cvlc) on Pi.")
        return

    cmd = player_cmd + [
        "--fullscreen",
        "--no-audio",
        "--no-video-title-show",
        "--quiet",
        video_path,
    ]

    with video_process_lock:
        _stop_external_vlc_locked()
        try:
            current_vlc_process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info(f"Started external VLC for {video_file}")
            print(f"Switched to: {video_file}")
        except Exception as e:
            current_vlc_process = None
            logger.error(f"Failed to start external VLC for {video_file}: {e}")
            print(f"Error: Could not play video {video_file}")


def queue_video_play(video_file):
    """Queue a video request; keep latest requests flowing without blocking."""
    try:
        video_queue.put_nowait(video_file)
    except queue.Full:
        try:
            video_queue.get_nowait()  # drop oldest
            video_queue.put_nowait(video_file)
        except Exception:
            logger.warning("Video queue full; dropping request")


def video_playback_worker():
    """Single worker that executes play_video to avoid concurrent VLC switches."""
    logger.info("Video playback worker started")
    while True:
        video_file = None
        try:
            video_file = video_queue.get()
            play_video_safe(video_file)
        except Exception as e:
            logger.error(f"Video playback worker error: {e}")
        finally:
            if video_file is not None:
                video_queue.task_done()

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


def _interface_has_ip(interface_name, ip_address):
    """Return True if interface already has the target IPv4 address."""
    try:
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "dev", interface_name],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        return ip_address in result.stdout
    except Exception:
        return False


def ensure_pi_ip_for_modbus():
    """Ensure eth0 has 192.168.1.10/24 before trying Modbus connection."""
    if not sys.platform.startswith("linux"):
        logger.info("Skipping IP setup (non-Linux platform)")
        return True

    if _interface_has_ip(PI_ETH_INTERFACE, PI_IP):
        logger.info(f"{PI_ETH_INTERFACE} already has {PI_IP_CIDR}")
        print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
        return True

    print(f"Configuring network: assigning {PI_IP_CIDR} to {PI_ETH_INTERFACE}...")
    logger.info(f"Assigning {PI_IP_CIDR} to {PI_ETH_INTERFACE}")

    commands = [
        ["ip", "addr", "add", PI_IP_CIDR, "dev", PI_ETH_INTERFACE],
        ["sudo", "-n", "ip", "addr", "add", PI_IP_CIDR, "dev", PI_ETH_INTERFACE],
    ]

    for cmd in commands:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            output = (result.stdout or "") + (result.stderr or "")

            if result.returncode == 0:
                logger.info(f"IP assignment successful using: {' '.join(cmd)}")
                print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
                return True

            if "Address already assigned" in output:
                logger.info(f"IP already assigned on {PI_ETH_INTERFACE}")
                print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
                return True

        except FileNotFoundError:
            logger.warning(f"Command not found: {' '.join(cmd)}")
            continue
        except Exception as exc:
            logger.warning(f"Error running {' '.join(cmd)}: {exc}")

    # Final verification after command attempts
    if _interface_has_ip(PI_ETH_INTERFACE, PI_IP):
        print(f"✓ Network ready: {PI_ETH_INTERFACE} has {PI_IP_CIDR}")
        return True

    print("\nCould not auto-configure Pi Ethernet IP for Modbus.")
    print(f"Run this once before starting: sudo ip addr add {PI_IP_CIDR} dev {PI_ETH_INTERFACE}")
    print("If it says 'Address already assigned', that is OK.")
    return False


def read_modbus_coils():
    """Read all configured coils from the PLC and return their states"""
    if not modbus_client or not modbus_client.is_socket_open():
        logger.warning("Modbus client not connected")
        return None
    
    try:
        # Read 5 coils starting from address 0
        result = modbus_client.read_coils(0, count=5)
        
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
        print(f"  -> Playing video: {video_file}")
        queue_video_play(video_file)
    else:
        logger.debug(f"Trigger for {action_name} ignored (cooldown active)")
        print(f"  -> Trigger ignored (cooldown: {COOLDOWN_SECONDS}s)")


def modbus_polling_loop():
    """Main loop that polls Modbus coils and triggers videos"""
    logger.info("Starting Modbus polling loop")
    print("[Modbus Monitor] Polling started - waiting for coil changes...\n")
    
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
                    print(f"[Coil {coil_addr}] State changed: OFF -> ON ({action_name})")
                    handle_modbus_trigger(action_name)
                # Also log falling edge for visibility
                elif not current_state and previous_state:
                    logger.info(f"Falling edge detected on coil {coil_addr} ({action_name})")
                    print(f"[Coil {coil_addr}] State changed: ON -> OFF ({action_name})")
                
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

    # Ensure Pi Ethernet IP is configured before Modbus TCP connect
    if not ensure_pi_ip_for_modbus():
        logger.error("Required Pi Ethernet IP is not configured")
        return
    
    # Connect to Modbus server
    print("=" * 60)
    print(f"Connecting to Modbus PLC at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}...")
    print("=" * 60)
    
    if not connect_modbus():
        logger.error("Failed to establish initial Modbus connection")
        print("\n" + "=" * 60)
        print("ERROR: MODBUS CONNECTION FAILED")
        print("=" * 60)
        print(f"Could not connect to {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
        print("\nPlease check:")
        print("  1. PLC is powered on")
        print("  2. Ethernet cable is connected")
        print("  3. Pi has IP 192.168.1.10 (run: ip -4 addr show dev eth0)")
        print("  4. PLC IP is correct: 192.168.1.100")
        print("  5. Modbus TCP is enabled on the LOGO! 8")
        print("=" * 60)
        return
    
    # Connection successful
    print("\n" + "=" * 60)
    print("✓ MODBUS CONNECTION SUCCESSFUL!")
    print("=" * 60)
    print(f"Connected to PLC at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
    print("Monitoring coils 0-4 for state changes...")
    print("=" * 60 + "\n")
    
    # Create GUI window (black fullscreen on Pi, embedded on Windows)
    root = init_video_window()

    # Start playback worker thread (serializes all play requests)
    playback_thread = threading.Thread(target=video_playback_worker, daemon=True)
    playback_thread.start()

    # Auto-play first video on startup
    logger.info("Auto-playing first video...")
    queue_video_play("Guide_steps.mp4")
    
    # Start Modbus polling in background thread
    modbus_thread = threading.Thread(target=modbus_polling_loop, daemon=True)
    modbus_thread.start()
    logger.info("Modbus polling thread started")
    
    # Run GUI main loop (if available)
    if root is not None:
        logger.info("Starting GUI main loop")
        try:
            root.mainloop()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    else:
        # No GUI - just wait for Modbus triggers
        logger.info("Running without GUI (console mode)")
        print("Press Ctrl+C to exit")
        try:
            modbus_thread.join()
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
    
    # Cleanup
    if USE_EXTERNAL_VLC:
        with video_process_lock:
            _stop_external_vlc_locked()

    if modbus_client:
        modbus_client.close()
    logger.info("Application shutdown complete")


if __name__ == "__main__":
    main()
