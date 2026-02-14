import sys
import time

try:
    from pymodbus.client import ModbusTcpClient
except ImportError:
    print("ERROR: pymodbus not installed. Install with: pip install pymodbus")
    sys.exit(1)

# Basic connection settings
MODBUS_SERVER_IP = "192.168.1.100"
MODBUS_SERVER_PORT = 502
MODBUS_UNIT_ID = 1

# What to read (coils 0-4 by default)
START_COIL = 0
COIL_COUNT = 5


def main():
    print(f"Connecting to Modbus server {MODBUS_SERVER_IP}:{MODBUS_SERVER_PORT} (unit {MODBUS_UNIT_ID})")
    client = ModbusTcpClient(MODBUS_SERVER_IP, port=MODBUS_SERVER_PORT)

    if not client.connect():
        print("ERROR: Could not connect to Modbus server.")
        sys.exit(2)

    try:
        while True:
            try:
                result = client.read_coils(address=START_COIL, count=COIL_COUNT, slave=MODBUS_UNIT_ID)
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
