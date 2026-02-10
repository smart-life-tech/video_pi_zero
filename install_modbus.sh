#!/bin/bash
# Installation script for Modbus dependencies on Raspberry Pi

echo "Installing pymodbus for Modbus TCP communication..."
echo "=================================================="

# Update pip
python3 -m pip install --upgrade pip

# Install pymodbus
python3 -m pip install pymodbus

# Verify installation
echo ""
echo "Verifying installation..."
python3 -c "import pymodbus; print(f'pymodbus version: {pymodbus.__version__}')" && echo "✓ pymodbus installed successfully!" || echo "✗ Installation failed"

echo ""
echo "Installation complete!"
echo "You can now run: python3 vid_modbus.py"
