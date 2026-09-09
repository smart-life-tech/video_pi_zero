# Data Integration Report: vid_modbus.py ↔ Flask Backend

**Date:** 2026-09-09  
**Purpose:** Map what data `vid_modbus.py` currently collects vs. what the Flask backend needs

---

## 📊 Data Requirements

The Flask backend needs to POST to `/api/v1/ingest/status` every 5 minutes:

```json
{
  "machineId": "hw-000123",
  "liquid": {
    "state": "ok" | "low",
    "percent": 0-100 | null
  },
  "firmware": "1.4.2",
  "ts": "2026-08-31T09:14:02Z"
}
```

---

## ✅ Data Already Available in vid_modbus.py

| Data Field | Source | Status | Notes |
|---|---|---|---|
| `machineId` | Environment variable | ✅ Ready | Not currently used; need to add as config |
| `firmware` | Code version | ❌ Hardcoded | Must be added to code (e.g., "1.4.2") |
| `ts` | System time | ✅ Ready | Python `datetime.now()` with UTC |
| **Modbus Connection** | PLC at 192.168.1.100:504 | ✅ Ready | Already connected and polling |
| **Coil States (0-4)** | PLC registers | ✅ Collected | Currently used only for video triggers |

---

## ❌ Data Missing - MUST BE ADDED

### 1. **Liquid Level State** (`liquid.state`: "ok" or "low")

**Currently:** Not collected from PLC  
**Needed:** Read from PLC Modbus register/coil  
**Question for you:** Which PLC register/coil holds the liquid level?
- Is it a **discrete coil** (digital on/off)?
- Is it a **holding register** (analog 0-65535)?
- What's the **address** (Modbus address)?

**Example mapping:**
- Coil 5 = "low" level warning
- Coil 6 = "ok" level normal

### 2. **Liquid Percent** (`liquid.percent`: 0-100)

**Currently:** Not collected from PLC  
**Needed:** Read from PLC and convert to 0-100%  
**Question for you:** 
- Which PLC register has the percentage/analog level?
- What's the **conversion formula**?
  - Example: If register gives 0-1024, do we map to 0-100%?
  - Example: If register gives 4-20mA analog scaled to 0-4095, how to convert?

**Example conversion function to add:**
```python
def read_liquid_level():
    """Read liquid level from PLC and return (state, percent)"""
    if not modbus_client:
        return None, None
    
    # TODO: Define actual addresses from PLC documentation
    PLC_LIQUID_REGISTER = 100  # NEED TO KNOW
    PLC_LOW_WARNING_COIL = 5   # NEED TO KNOW
    
    try:
        # Read the analog level
        result = modbus_client.read_holding_registers(PLC_LIQUID_REGISTER, count=1)
        if result.isError():
            return None, None
        
        raw_value = result.registers[0]
        percent = convert_raw_to_percent(raw_value)  # NEED FORMULA
        
        # Read low warning coil
        low_result = modbus_client.read_coils(PLC_LOW_WARNING_COIL, count=1)
        if low_result.isError():
            state = "ok"  # Default
        else:
            state = "low" if low_result.bits[0] else "ok"
        
        return state, percent
    except Exception as e:
        log.error(f"Liquid read error: {e}")
        return None, None

def convert_raw_to_percent(raw_value: int) -> int:
    """Convert PLC raw value to 0-100 percent.
    
    TODO: DEFINE THIS BASED ON YOUR SENSOR
    
    Example conversions:
    - If 0-4095 ADC: percent = (raw / 4095) * 100
    - If 4-20mA on 0-4095 scale: percent = ((raw - 204) / 3276) * 100
    - If 0-1024: percent = (raw / 1024) * 100
    """
    # PLACEHOLDER - REPLACE WITH YOUR FORMULA
    return min(100, max(0, int((raw_value / 4095.0) * 100)))
```

### 3. **Firmware Version** (`firmware`: "1.4.2")

**Currently:** Not in code  
**Needed:** Add version string to code or query PLC  
**Options:**
- Option A: Hardcode in `vid_modbus.py` as a constant
- Option B: Query PLC for firmware version (if PLC stores it)
- Option C: Read from file/environment variable

**Recommended:** Add to environment:
```bash
export FIRMWARE_VERSION="1.4.2"
```

Then in code:
```python
FIRMWARE_VERSION = os.environ.get("FIRMWARE_VERSION", "1.0.0")
```

---

## 🔧 What NEEDS TO BE ADDED to vid_modbus.py

### Changes Required:

1. **Add HTTP client** - POST to backend
```python
import requests  # Add to imports
import json
from datetime import datetime, timezone

BACKEND_API_URL = os.environ.get("BACKEND_API_URL", "http://127.0.0.1:5000")
MACHINE_ID = os.environ.get("MACHINE_ID", "hw-000123")
FIRMWARE_VERSION = os.environ.get("FIRMWARE_VERSION", "1.0.0")
DEVICE_SECRET = os.environ.get("DEVICE_SECRET", "")  # For HMAC signing
```

2. **Add liquid level reading function** (template above)

3. **Add backend posting function**
```python
def post_to_backend(state: str, percent: int):
    """POST reading to Flask backend every 5 minutes"""
    payload = {
        "machineId": MACHINE_ID,
        "liquid": {
            "state": state,
            "percent": percent
        },
        "firmware": FIRMWARE_VERSION,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    }
    
    # Sign the request (HMAC-SHA256)
    body = json.dumps(payload, separators=(',', ':')).encode()
    import hashlib, hmac, time
    
    ts = int(time.time())
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = '\n'.join(['POST', '/api/v1/ingest/status', str(ts), MACHINE_ID, body_hash])
    signature = hmac.new(DEVICE_SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    
    try:
        response = requests.post(
            f"{BACKEND_API_URL}/api/v1/ingest/status",
            data=body,
            headers={
                'Content-Type': 'application/json; charset=utf-8',
                'X-HW-Device-Id': MACHINE_ID,
                'X-HW-Timestamp': str(ts),
                'X-HW-Key-Id': 'v1',
                'X-HW-Signature': signature
            },
            timeout=10
        )
        log.info(f"Backend POST: {response.status_code}")
    except Exception as e:
        log.error(f"Backend POST failed: {e}")
```

4. **Add periodic posting** - Call every 5 minutes in main loop

5. **Configuration additions to .env or environment:**
```bash
# Machine identification
MACHINE_ID=hw-000123
FIRMWARE_VERSION=1.4.2
DEVICE_SECRET=super-secret-key  # Must match backend

# Backend connection
BACKEND_API_URL=http://localhost:5000  # Or production URL
BACKEND_POST_INTERVAL=300  # Seconds (5 minutes)

# PLC Modbus addresses (YOU MUST PROVIDE THESE)
PLC_LIQUID_LEVEL_REGISTER=100      # TODO: GET FROM YOUR PLC DOCS
PLC_LIQUID_STATE_COIL=5            # TODO: GET FROM YOUR PLC DOCS
PLC_LIQUID_MIN_RAW=0               # TODO: GET FROM YOUR PLC DOCS
PLC_LIQUID_MAX_RAW=4095            # TODO: GET FROM YOUR PLC DOCS
```

---

## ❓ QUESTIONS FOR YOU - PLC DOCUMENTATION NEEDED

**I need answers to these to complete the integration:**

1. **Liquid Level Sensor**
   - [ ] Which Modbus register/coil has the liquid level?
   - [ ] Is it a coil (0-1, digital) or register (0-65535, analog)?
   - [ ] What's the memory address (Modbus address)?

2. **Low Level Warning**
   - [ ] Is there a separate "low level" coil?
   - [ ] Or does the percent value determine the state?
   - [ ] What's the threshold? (e.g., <= 10% = "low")

3. **Sensor Conversion**
   - [ ] What's the raw value range? (e.g., 0-4095, 0-1024, 4-20mA)
   - [ ] What's the conversion formula to get 0-100%?
   - [ ] Is there a calibration? (e.g., min raw = empty, max raw = full)

4. **Firmware**
   - [ ] Where does firmware version come from?
   - [ ] Is it stored in a PLC register we can read?
   - [ ] Or should it be hardcoded/configured?

5. **Backend Connection**
   - [ ] Where will the backend run? (PythonAnywhere, local, etc.)
   - [ ] What's the API base URL for posting?
   - [ ] What's the shared secret (DEVICE_SECRET) for HMAC signing?

---

## 📋 Integration Checklist

- [ ] Liquid level register address obtained
- [ ] Low level indicator identified
- [ ] Conversion formula defined
- [ ] Firmware version source determined
- [ ] Backend API URL known
- [ ] Device secret (HMAC key) generated
- [ ] Machine ID assigned (hw-000123)
- [ ] Code added to vid_modbus.py
- [ ] Environment variables configured
- [ ] Posted data tested and validated

---

## 🚀 Implementation Order

1. **Get PLC Documentation** - Answer the questions above
2. **Add Liquid Reading** - Implement `read_liquid_level()` function
3. **Add Backend Posting** - Implement `post_to_backend()` function
4. **Add Environment Config** - Set MACHINE_ID, FIRMWARE_VERSION, etc.
5. **Test Locally** - Verify POST data format matches backend
6. **Deploy** - Push to Pi, configure backend connection

---

## 📝 Code Location

All new code should go in `vid_modbus.py` around line 250-300 (in CONFIG section for new constants, then functions after helpers).

See `../flask_backend/README.md` for full backend API spec and testing examples.

---

## Next Steps

1. **Provide PLC Modbus mapping** (register addresses + conversion)
2. **I'll add the code** to read liquid level and post to backend
3. **You configure environment variables** on the Pi
4. **Test the integration** with live data flow
