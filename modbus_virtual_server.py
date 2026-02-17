"""
Virtual Modbus TCP Server for Testing
Simulates a Siemens LOGO! 8 PLC with 5 coils
"""
import sys
import time
import logging
from threading import Thread

try:
    from pymodbus.server import StartTcpServer
    from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
    from pymodbus.datastore import ModbusSequentialDataBlock
except ImportError:
    print("ERROR: pymodbus not installed. Install with: pip install pymodbus")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Server configuration
SERVER_IP = "0.0.0.0"  # Listen on all interfaces
SERVER_PORT = 502  # Standard Modbus TCP port (use 5020 if you don't have admin rights)
UNIT_ID = 1

def create_modbus_context():
    """
    Create a Modbus datastore with initial values
    - 16 coils (binary outputs): addresses 0-15
    - 16 discrete inputs: addresses 0-15
    - 16 holding registers: addresses 0-15
    - 16 input registers: addresses 0-15
    """
    # Initialize all coils to False (0)
    coils = ModbusSequentialDataBlock(0, [0] * 16)
    
    # Initialize discrete inputs
    discrete_inputs = ModbusSequentialDataBlock(0, [0] * 16)
    
    # Initialize holding registers
    holding_registers = ModbusSequentialDataBlock(0, [0] * 16)
    
    # Initialize input registers
    input_registers = ModbusSequentialDataBlock(0, [0] * 16)
    
    # Create the slave context
    slave_context = ModbusSlaveContext(
        di=discrete_inputs,  # Discrete Inputs
        co=coils,           # Coils
        hr=holding_registers,  # Holding Registers
        ir=input_registers   # Input Registers
    )
    
    # Create the server context with the slave context
    # The single=True means we only have one unit ID
    context = ModbusServerContext(slaves={UNIT_ID: slave_context}, single=False)
    
    return context


def simulate_coil_changes(context):
    """
    Simulate coil changes to test the client
    This function runs in a separate thread and periodically toggles coils
    """
    logger.info("Simulation thread started - will toggle coils every 5 seconds")
    time.sleep(3)  # Wait for server to fully start
    
    coil_sequence = [
        [1, 0, 0, 0, 0],  # Coil 0 ON (Process_step_1)
        [0, 1, 0, 0, 0],  # Coil 1 ON (Guide_steps)
        [0, 0, 1, 0, 0],  # Coil 2 ON (Warning)
        [0, 0, 0, 1, 0],  # Coil 3 ON (Process_step_2)
        [0, 0, 0, 0, 1],  # Coil 4 ON (Process_step_3)
        [0, 0, 0, 0, 0],  # All OFF
    ]
    
    idx = 0
    while True:
        try:
            # Get the slave context
            slave_context = context[UNIT_ID]
            
            # Set the coil values
            values = coil_sequence[idx]
            for i, value in enumerate(values):
                slave_context.setValues(1, i, [value])  # 1 = coils
            
            logger.info(f"Set coils 0-4 to: {values}")
            
            idx = (idx + 1) % len(coil_sequence)
            time.sleep(5)  # Wait 5 seconds before next change
            
        except Exception as e:
            logger.error(f"Error in simulation thread: {e}")
            time.sleep(1)


def main():
    print("=" * 60)
    print("Virtual Modbus TCP Server")
    print("=" * 60)
    print(f"Server Address: {SERVER_IP}:{SERVER_PORT}")
    print(f"Unit ID: {UNIT_ID}")
    print(f"Coils available: 0-15 (your client uses 0-4)")
    print()
    print("The server will automatically cycle through coils 0-4")
    print("to simulate PLC button presses every 5 seconds.")
    print()
    print("To test manually, use a Modbus client tool to write coils.")
    print("Press Ctrl+C to stop the server.")
    print("=" * 60)
    
    # Create the Modbus datastore
    context = create_modbus_context()
    
    # Start simulation thread
    sim_thread = Thread(target=simulate_coil_changes, args=(context,), daemon=True)
    sim_thread.start()
    
    # Start the Modbus TCP server
    try:
        logger.info(f"Starting Modbus TCP server on {SERVER_IP}:{SERVER_PORT}")
        StartTcpServer(
            context=context,
            address=(SERVER_IP, SERVER_PORT)
        )
    except PermissionError:
        logger.error(f"Permission denied to bind to port {SERVER_PORT}.")
        logger.error("Try running as administrator, or change SERVER_PORT to 5020 in the script.")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
