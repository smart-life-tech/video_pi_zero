# Network Setup for PLC Connection

## Problem
Your Raspberry Pi's `eth0` (Ethernet) interface has no IP address. The PLC is at `192.168.1.100`, so your Pi needs an IP in the `192.168.1.x` subnet to communicate.

## Quick Fix (Temporary - until reboot)

Run on your Raspberry Pi:
```bash
sudo ip addr add 192.168.1.10/24 dev eth0
sudo ip link set eth0 up
ping 192.168.1.100
```

Or use the provided script:
```bash
chmod +x setup_ethernet.sh
./setup_ethernet.sh
```

## Permanent Fix

Edit the network configuration:
```bash
sudo nano /etc/dhcpcd.conf
```

Add these lines at the end:
```
interface eth0
static ip_address=192.168.1.10/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1 8.8.8.8
```

Save (Ctrl+X, Y, Enter) and reboot:
```bash
sudo reboot
```

## Verify Connection

After setup, verify:
```bash
ifconfig eth0        # Should show 192.168.1.10
ping 192.168.1.100   # Should reach the PLC
```

## Test Modbus Connection

Once network is configured:
```bash
python modbus_test.py
```

Update `MODBUS_SERVER_IP` in your scripts from `127.0.0.1` to `192.168.1.100`.
