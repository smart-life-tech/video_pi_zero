"""
Manual Modbus Coil Control Tool
Use this to manually trigger coils on the virtual Modbus server or real PLC
"""
import sys
import time

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("ERROR: pymodbus not installed. Install with: pip install pymodbus")
    sys.exit(1)

# Configuration
MODBUS_SERVER_IP = "192.168.1.100"  # PLC IP address (use "127.0.0.1" for virtual server)
MODBUS_SERVER_PORT = 502
MODBUS_UNIT_ID = 1

# Coil mappings
COIL_NAMES = {
    0: "Process_step_1",
    1: "Guide_steps",
    2: "Warning",
    3: "Process_step_2",
    4: "Process_step_3",
}


def read_coils(client, start=0, count=5):
    """Read coil states"""
    result = client.read_coils(address=start, count=count, unit=MODBUS_UNIT_ID)
    if result.isError():
        print(f"ERROR reading coils: {result}")
        return None
    return result.bits[:count]


def write_coil(client, coil_address, value):
    """Write a single coil"""
    result = client.write_coil(address=coil_address, value=value, unit=MODBUS_UNIT_ID)
    if result.isError():
        print(f"ERROR writing coil {coil_address}: {result}")
        return False
    return True


def write_multiple_coils(client, start_address, values):
    """Write multiple coils at once"""
    result = client.write_coils(address=start_address, values=values, unit=MODBUS_UNIT_ID)
    if result.isError():
        print(f"ERROR writing coils: {result}")
        return False
    return True


def display_status(client):
    """Display current coil states"""
    states = read_coils(client, 0, 5)
    if states is None:
        return
    
    print("\nCurrent Coil States:")
    print("-" * 40)
    for i, state in enumerate(states):
        name = COIL_NAMES.get(i, f"Coil {i}")
        status = "ON " if state else "OFF"
        print(f"  {i}: {name:20s} [{status}]")
    print("-" * 40)


def main():
    print("=" * 60)
    print("Manual Modbus Coil Control Tool")
    print("=" * 60)
    print(f"Connecting to: {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
    print()
    
    # Connect to Modbus server
    client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT)
    if not client.connect():
        print("ERROR: Could not connect to Modbus server.")
        print("Make sure the virtual server is running: python modbus_virtual_server.py")
        sys.exit(1)
    
    print("Connected successfully!")
    
    try:
        while True:
            display_status(client)
            print("\nCommands:")
            print("  0-4: Toggle coil 0-4")
            print("  a  : Turn all coils ON")
            print("  c  : Clear all coils (turn OFF)")
            print("  r  : Refresh status")
            print("  q  : Quit")
            print()
            
            cmd = input("Enter command: ").strip().lower()
            
            if cmd == 'q':
                break
            elif cmd == 'r':
                continue
            elif cmd == 'a':
                if write_multiple_coils(client, 0, [True] * 5):
                    print("✓ All coils turned ON")
            elif cmd == 'c':
                if write_multiple_coils(client, 0, [False] * 5):
                    print("✓ All coils turned OFF")
            elif cmd.isdigit() and 0 <= int(cmd) <= 4:
                coil = int(cmd)
                # Read current state
                states = read_coils(client, 0, 5)
                if states:
                    new_value = not states[coil]
                    if write_coil(client, coil, new_value):
                        print(f"✓ Coil {coil} ({COIL_NAMES[coil]}) turned {'ON' if new_value else 'OFF'}")
            else:
                print("Invalid command")
            
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\nExiting...")
    finally:
        client.close()
        print("Connection closed")


if __name__ == "__main__":
    main()
