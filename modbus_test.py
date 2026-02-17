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
MODBUS_SERVER_PORT = 502
MODBUS_UNIT_ID = 1

# What to read (coils 0-4 by default)
START_COIL = 0
COIL_COUNT = 5


def main():

    print_available_network_ips()
    print(f"Connecting to Modbus server {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT} (unit {MODBUS_UNIT_ID})")
    client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT)
    if not client.connect():
        print("ERROR: Could not connect to Modbus server. Check if PLC is on the same network and cable is connected.")
        sys.exit(2)

    try:
        while True:
            try:
                result = client.read_coils(START_COIL, COIL_COUNT)
                if result.isError():
                    print(f"ERROR: Modbus read failed: {result}")
                else:
                    states = result.bits[:COIL_COUNT]
                    print(f"Read coils {START_COIL}-{START_COIL + COIL_COUNT - 1}: {states}")
            except Exception as e:
                print(f"Exception during Modbus read: {e}")
            time.sleep(1)  # Wait before next read
    finally:
        client.close()
        time.sleep(0.1)


if __name__ == "__main__":
    main()

