# Instructions for PLC Programmer - Siemens LOGO! 8 Modbus TCP Configuration

## Project Overview
We are integrating a Raspberry Pi video player with a Siemens LOGO! 8 PLC via Modbus TCP communication. The Pi will monitor specific Modbus coils and play different videos when the PLC sets these coils to TRUE.

---

## Network Configuration Required

### Raspberry Pi Settings:
- **Expected IP Address**: To be determined (suggest static IP for reliability)
- **Modbus Role**: Modbus TCP **Client** (reads from PLC)

### Siemens LOGO! 8 Settings:
- **IP Address**: `192.168.1.100` (or provide your actual IP)
- **Subnet Mask**: `255.255.255.0`
- **Modbus TCP Port**: `502` (default)
- **Modbus Role**: Modbus TCP **Server**
- **Unit ID (Slave ID)**: `1`

**ACTION REQUIRED**: Please confirm or adjust the LOGO! 8 IP address and network settings.

---

## Modbus Register/Coil Mapping

The Raspberry Pi will poll the following **Modbus Coils** (discrete outputs):

| Coil Address | Function | Video Triggered | Description |
|--------------|----------|-----------------|-------------|
| **0** | Trigger Video 1 | Process_step_1.mp4 | Main process step 1 |
| **1** | Trigger Video 2 | Guide_steps.mp4 | Guidance/tutorial video |
| **2** | Trigger Video 3 | Warning.mp4 | Warning or alert video |
| **3** | Trigger Video 4 | Process_step_2.mp4 | Main process step 2 |
| **4** | Trigger Video 5 | Process_step_3.mp4 | Main process step 3 |

**Note**: Coil addresses use **0-based indexing** in Modbus protocol.

---

## PLC Programming Requirements

### 1. Enable Modbus TCP on LOGO! 8
- In LOGO!Soft Comfort, enable Ethernet communication
- Configure Modbus TCP Server mode
- Assign the IP address and ensure it's accessible from the Raspberry Pi

### 2. Configure Network Blocks (NI)
Create **Network Output (NQ)** blocks in your LOGO! program for each coil:
- **NQ1** → Coil 0 (Process_step_1)
- **NQ2** → Coil 1 (Guide_steps)
- **NQ3** → Coil 2 (Warning)
- **NQ4** → Coil 3 (Process_step_2)
- **NQ5** → Coil 4 (Process_step_3)

### 3. Trigger Logic
The Raspberry Pi detects **rising edge** transitions (0 → 1). When you want to trigger a video:

**Option A - Momentary Pulse (Recommended)**:
```
[Your Condition] → [Pulse Generator 0.5s] → [NQ1]
```
- Set the coil HIGH for at least 200ms
- The Pi will detect the rising edge and play the video
- You can reset the coil to LOW after that

**Option B - Latched Signal**:
```
[Your Condition] → [Set/Reset Latch] → [NQ1]
```
- Set coil HIGH when you want to trigger
- Keep it HIGH for at least 200ms
- Reset to LOW when done
- The Pi only triggers on the 0→1 transition

**IMPORTANT**: 
- Each trigger should be a **distinct pulse** (going from LOW to HIGH)
- Keeping a coil constantly HIGH will NOT retrigger the video
- Video cooldown period is **5 seconds** - triggering the same coil again within 5 seconds will be ignored

### 4. Example Use Cases

**Scenario 1**: Sequential Process Steps
```
[Start Button] → [Step 1 Complete] → Pulse on NQ1 (Process_step_1)
                → [Step 2 Complete] → Pulse on NQ4 (Process_step_2)
                → [Step 3 Complete] → Pulse on NQ5 (Process_step_3)
```

**Scenario 2**: Warning on Fault Condition
```
[Safety Sensor Triggered] → Pulse on NQ3 (Warning)
```

**Scenario 3**: Guidance on Button Press
```
[Help Button] → Pulse Generator → NQ2 (Guide_steps)
```

---

## Testing Procedure

### Phase 1: Communication Test
1. Power on LOGO! 8 and configure network settings
2. Verify Raspberry Pi can ping the LOGO! IP address:
   ```bash
   ping 192.168.1.100
   ```
3. Run the Python script on the Pi:
   ```bash
   python vid_modbus.py
   ```
4. Check for "Successfully connected to Modbus server" message

### Phase 2: Coil Reading Test
1. Manually set NQ1-NQ5 to HIGH in LOGO!Soft Comfort (online mode)
2. Observe the Pi console/log for detection messages
3. Verify videos play when coils transition from LOW to HIGH

### Phase 3: Integration Test
1. Implement your actual PLC logic with pulse generators
2. Trigger each condition and verify correct videos play
3. Test cooldown behavior (rapid triggers should be ignored)
4. Test edge cases (power loss, network interruption, reconnection)

---

## Troubleshooting Guide

### Issue: Raspberry Pi cannot connect to LOGO!
**Check**:
- Is Modbus TCP enabled on LOGO! 8?
- Are both devices on the same network/subnet?
- Is the IP address correct in `vid_modbus.py`?
- Firewall blocking port 502?

### Issue: Videos don't play when coil is set
**Check**:
- Is the coil transitioning from LOW→HIGH (not already HIGH)?
- Is the coil HIGH for at least 200ms?
- Check Pi console logs for trigger detection
- Verify video files exist in the correct folder

### Issue: Videos trigger multiple times
**Check**:
- Are you creating a pulse or holding the coil HIGH continuously?
- Remove any oscillating logic around the coil outputs
- Use pulse generators with minimum 200ms, maximum 1s duration

### Issue: Some triggers are ignored
**Check**:
- Are you triggering faster than the 5-second cooldown?
- Check Pi logs for "cooldown" or "debounce" messages

---

## Communication Protocol Details

**Modbus Function Code Used**: 
- Function Code 1 (Read Coils)

**Polling Rate**: 
- The Pi polls coils every **100ms**

**Connection Type**: 
- Modbus TCP (not RTU)
- No serial cable needed - Ethernet only

**Data Type**: 
- Boolean coils (ON/OFF), not registers

---

## Contact Information

For questions or adjustments to the coil mapping, contact:
- **Raspberry Pi Developer**: [Your contact info]
- **PLC Programmer**: [PLC programmer contact info]

---

## Configuration File Settings

If you need to change settings, edit these variables in `vid_modbus.py`:

```python
MODBUS_SERVER_IP = "192.168.1.100"  # Your LOGO! IP
MODBUS_SERVER_PORT = 502
MODBUS_UNIT_ID = 1

# Coil address mapping (change if needed)
MODBUS_COILS = {
    "Process_step_1": 0,
    "Guide_steps": 1,
    "Warning": 2,
    "Process_step_2": 3,
    "Process_step_3": 4,
}
```

---

## Quick Reference: LOGO! 8 Modbus Coil Addresses

| LOGO! Block | Modbus Address | Function |
|-------------|----------------|----------|
| NQ1 | 0 | Video 1 (Process Step 1) |
| NQ2 | 1 | Video 2 (Guide) |
| NQ3 | 2 | Video 3 (Warning) |
| NQ4 | 3 | Video 4 (Process Step 2) |
| NQ5 | 4 | Video 5 (Process Step 3) |

**Remember**: LOGO! Network Outputs (NQ) map directly to Modbus coils when Modbus TCP server is enabled.

---

*Last Updated: February 10, 2026*
