#!/bin/bash
# Setup static IP on eth0 to communicate with PLC at 192.168.1.100

echo "==================================================================="
echo "Setting up Ethernet connection to PLC"
echo "==================================================================="
echo "PLC IP: 192.168.1.100"
echo "Pi will use: 192.168.1.10"
echo ""

# Temporary setup (until reboot)
echo "Applying temporary IP configuration..."
sudo ip addr add 192.168.1.10/24 dev eth0
sudo ip link set eth0 up

echo ""
echo "Current eth0 status:"
ip addr show eth0

echo ""
echo "Testing connection to PLC..."
ping -c 3 192.168.1.100

echo ""
echo "==================================================================="
echo "Temporary setup complete! To make this permanent, edit:"
echo "  sudo nano /etc/dhcpcd.conf"
echo ""
echo "Add these lines at the end:"
echo ""
echo "  interface eth0"
echo "  static ip_address=192.168.1.10/24"
echo "  static routers=192.168.1.1"
echo ""
echo "Then reboot: sudo reboot"
echo "==================================================================="
