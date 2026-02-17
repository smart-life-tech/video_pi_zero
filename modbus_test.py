import sys
import time

import socket
import psutil

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("ERROR: pymodbus not installed. Install with: pip install pymodbus")
    sys.exit(1)
# Utility function to print all available network IPs
def print_available_network_ips():
    print("Available network interfaces and IP addresses:")
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    print(f"  Interface: {iface}  IP: {addr.address}")
    except Exception as e:
        print(f"Could not list network interfaces: {e}")

# Basic connection settings
MODBUS_SERVER_IP = "192.168.1.100"  # PLC IP address (use "127.0.0.1" for virtual server)
MODBUS_SERVER_PORT = 504
MODBUS_UNIT_ID = 1

# What to read (coils 0-4 by default)
START_COIL = 0
COIL_COUNT = 5


def main():

    print_available_network_ips()
    print(f"Connecting to Modbus server {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT} (unit {MODBUS_UNIT_ID})")
    client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT)
    
    connected = client.connect()
    if not connected:
        print("=" * 60)
        print("ERROR: Could not connect to Modbus server.")
        print("=" * 60)
        print("Check:")
        print("  - PLC is powered on")
        print("  - Ethernet cable is connected")
        print("  - PLC IP is 192.168.1.100")
        print("  - Pi IP is 192.168.1.10 (shown above)")
        print("=" * 60)
        sys.exit(2)
    
    print("=" * 60)
    print("✓ CONNECTION SUCCESSFUL!")
    print("=" * 60)
    print(f"Connected to PLC at {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT}")
    print("Reading coils...")
    print("=" * 60)

    try:
        while True:
            try:
                result = client.read_coils(START_COIL, count=COIL_COUNT)
                if result.isError():
                    print(f"ERROR: Modbus read failed: {result}")
                else:
                    states = result.bits[:COIL_COUNT]
                    print(f"Read coils {START_COIL}-{START_COIL + COIL_COUNT - 1}: {states}")
            except Exception as e:
                print(f"Exception during Modbus read: {e}")
            time.sleep(1)  # Wait before next read
    except KeyboardInterrupt:
        print("\n\nStopping...")
    finally:
        client.close()
        print("Connection closed")
        time.sleep(0.1)


if __name__ == "__main__":
    main()

