# Flask Backend for Liquid Level Monitoring

Complete Flask backend implementing the [API contract](../BACKEND_CONTRACT.md).

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

**Key things to set:**
- `SECRET_KEY` - Random string for JWT signing
- `DATABASE_URL` - Database connection (SQLite for dev, PostgreSQL for production)
- `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` - For Web Push
- `FRONTEND_ORIGIN` - Your app's domain (for CORS)

### 3. Initialize database

```bash
python database.py init
```

### 4. Add your first machine

```bash
python database.py seed hw-000123 "My Machine" "super-secret-key"
```

The secret must match what's in your Pi's firmware.

### 5. Generate pairing codes

```bash
python database.py codes hw-000123 5
```

Print these on your machine's sticker. Each code is single-use.

### 6. Run the server

**Development:**
```bash
python app.py
```

Server runs on `http://localhost:5000`

**Production:**
```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Deployment to PythonAnywhere

### Setup

1. **Create account and web app**
   - Sign up at pythonanywhere.com
   - Create a web app (Flask)
   - Python version 3.9+

2. **Upload code**
   ```bash
   git clone <your-repo> /home/username/mysite
   cd /home/username/mysite
   ```

3. **Configure virtual environment**
   - In PythonAnywhere web app settings, point to virtual env
   - Or create one:
   ```bash
   mkvirtualenv --python=/usr/bin/python3.9 mysite
   pip install -r requirements.txt
   ```

4. **Set environment variables**
   - In PythonAnywhere web app settings, add to WSGI configuration:
   ```python
   import os
   os.environ['SECRET_KEY'] = 'your-secret'
   os.environ['VAPID_PRIVATE_KEY'] = 'your-key'
   os.environ['DATABASE_URL'] = 'sqlite:///home/username/mysite/backend.db'
   os.environ['FRONTEND_ORIGIN'] = 'https://yourdomain.com'
   ```

5. **Initialize database**
   - In PythonAnywhere bash:
   ```bash
   cd /home/username/mysite
   workon mysite
   python database.py init
   python database.py seed hw-000123 "Name" "secret"
   python database.py codes hw-000123
   ```

6. **Configure WSGI file**
   - Edit the WSGI file to import from your app:
   ```python
   import sys
   path = '/home/username/mysite'
   if path not in sys.path:
       sys.path.append(path)
   from app import create_app
   application = create_app()
   ```

7. **Reload web app**
   - Click "Reload" in PythonAnywhere web app settings

### Database

For small deployments, SQLite works fine. For production scale, use PostgreSQL:

```bash
# In PythonAnywhere bash
pip install psycopg2-binary
```

Then set `DATABASE_URL=postgresql://user:pass@host/dbname`

## Machine Provisioning

Each physical machine needs:

1. **Machine ID** - hw-000123 format
2. **Shared secret** - Matches Pi's firmware for HMAC signing
3. **Pairing codes** - Print on machine sticker, single-use

```bash
# Create a machine
python database.py seed hw-000456 "Genesis — Moto Zagos" "my-shared-secret"

# Generate 5 pairing codes
python database.py codes hw-000456 5
```

## API Endpoints

All endpoints are under `/api/v1`:

| Endpoint | Auth | From | Description |
| --- | --- | --- | --- |
| `POST /pairing/redeem` | None | App | Enter pairing code |
| `GET /machines/{id}/status` | Bearer | App | Poll machine state (every 30s) |
| `GET /push/vapid-public-key` | None | App | Get Web Push public key |
| `POST /push/subscriptions` | Bearer | App | Register for notifications |
| `DELETE /push/subscriptions` | Bearer | App | Unregister from notifications |
| `POST /ingest/status` | HMAC | Pi | Pi posts reading (every 5 min) |
| `GET /machines/{id}/stream` | Bearer | App | Optional: Server-sent events |

## Testing

### Test the Pi endpoint

```python
import hashlib, hmac, json, requests, time

API = 'http://localhost:5000'
DEVICE_ID = 'hw-000123'
SECRET = 'super-secret-key'

payload = {
    "machineId": DEVICE_ID,
    "liquid": {"state": "low", "percent": 8},
    "firmware": "1.4.2",
    "ts": "2026-08-31T09:14:02Z"
}

body = json.dumps(payload, separators=(',', ':')).encode()
ts = int(time.time())
body_hash = hashlib.sha256(body).hexdigest()

canonical = '\n'.join(['POST', '/api/v1/ingest/status', str(ts), DEVICE_ID, body_hash])
signature = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()

response = requests.post(
    f'{API}/api/v1/ingest/status',
    data=body,
    headers={
        'Content-Type': 'application/json; charset=utf-8',
        'X-HW-Device-Id': DEVICE_ID,
        'X-HW-Timestamp': str(ts),
        'X-HW-Key-Id': 'v1',
        'X-HW-Signature': signature
    }
)

print(response.status_code)
print(response.text)
```

### Test pairing

```python
import requests

response = requests.post(
    'http://localhost:5000/api/v1/pairing/redeem',
    json={'code': 'GEN-4821'}
)

print(response.json())
# Returns: {machineId, name, accessToken}
```

### Test status endpoint

```python
import requests

access_token = '...'  # From pairing

response = requests.get(
    'http://localhost:5000/api/v1/machines/hw-000123/status',
    headers={'Authorization': f'Bearer {access_token}'}
)

print(response.json())
# Returns: {machineId, name, liquid: {state, percent, percentAvailable}, lastSeenAt, updatedAt}
```

## State Machine

The backend maintains a confirmed state (ok, warn, low) based on Pi readings:

- **ok → warn**: percent ≤ 40%
- **warn → low**: percent ≤ 10% AND pi.state == 'low'
- **low → warn**: percent ≥ 20%
- **warn → ok**: percent ≥ 50% AND pi.state == 'ok'

Anti-flapping: require 3 consecutive readings confirming the transition.

Machines with no level sensor (percent: null) never show warn, only ok or low.

## Notifications

Web Push notifications are sent:
- Only when level drops (ok→warn, warn→low)
- Reminder every 12 hours while machine stays in low state
- One subscription per endpoint (idempotent)

Subscriptions are stored in the database and can be deleted via API.

## Logs and Debugging

Check logs for:
- Signature verification failures → check device secret matches Pi
- State transitions → watch the state machine logic
- Push notification attempts → see send failures

```bash
# Tail logs
tail -f *.log

# Check database
sqlite3 backend.db 'SELECT * FROM machines;'
```

## Troubleshooting

**Pi signature fails with 401:**
- Device secret doesn't match Pi's firmware
- Clock on Pi is too far off (NTP issue)
- Check X-HW-Timestamp vs server time

**Status endpoint returns 403 wrong_machine:**
- Access token is for a different machine
- This is expected if you use wrong token

**No notifications sent:**
- Check VAPID_PRIVATE_KEY is set
- Verify subscription endpoints exist in database
- Check notification logs for failures

## Next Steps

1. Point your app at this backend: set API_BASE to your deployed URL
2. Flash your Pis with the firmware that posts to `/api/v1/ingest/status`
3. Generate pairing codes and attach to machines
4. Users scan code in app to pair
5. App gets live updates from backend

## Resources

- [API Contract](../BACKEND_CONTRACT.md) - Full specification
- [Flask docs](https://flask.palletsprojects.com/)
- [SQLAlchemy docs](https://docs.sqlalchemy.org/)
- [Web Push spec](https://www.w3.org/TR/push-api/)
