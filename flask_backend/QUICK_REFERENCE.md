# Quick Reference - Flask Backend Commands

## Local Development Setup

```bash
# One-time setup
./setup.sh

# Or manual setup
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python database.py init
```

## Database Management

```bash
# Initialize (create tables)
python database.py init

# Add a machine
python database.py seed hw-000123 "Machine Name" "shared-secret"

# Generate pairing codes
python database.py codes hw-000123 5

# List all machines
python database.py machines

# Reset database (⚠️ deletes all data)
python database.py reset
```

## Running the Server

```bash
# Development (auto-reload, debug mode)
python app.py
# Server at: http://localhost:5000

# Production (gunicorn)
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

## Testing

```bash
# Run all tests
pytest test_api.py -v

# Test one function
pytest test_api.py::test_pairing_redeem -v

# Install pytest (if needed)
pip install pytest
```

## API Testing (with curl)

### Get VAPID Public Key
```bash
curl http://localhost:5000/api/v1/push/vapid-public-key
```

### Redeem Pairing Code
```bash
curl -X POST http://localhost:5000/api/v1/pairing/redeem \
  -H "Content-Type: application/json" \
  -d '{"code": "GEN4821"}'
```

### Get Machine Status
```bash
ACCESS_TOKEN="eyJ0eXAi..."  # From pairing redeem
curl -H "Authorization: Bearer $ACCESS_TOKEN" \
  http://localhost:5000/api/v1/machines/hw-000123/status
```

### Subscribe to Push (Register Device)
```bash
curl -X POST http://localhost:5000/api/v1/push/subscriptions \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "machineId": "hw-000123",
    "subscription": {
      "endpoint": "https://fcm.googleapis.com/fcm/send/...",
      "expirationTime": null,
      "keys": {
        "p256dh": "BNcRdreALRFX...",
        "auth": "tBHItJI5svbpez7KI4CCXg"
      }
    },
    "platform": "android"
  }'
```

### Post Reading from Pi (HMAC-signed)
See `auth.py` for signing logic. Example Python script in `README.md`.

## Environment Configuration

```bash
# Edit configuration
nano .env

# Key variables needed:
# - SECRET_KEY (generate: python3 -c "import secrets; print(secrets.token_urlsafe(32))")
# - VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY
# - FRONTEND_ORIGIN
# - DATABASE_URL
```

## Generate VAPID Keys

```bash
python3 << 'EOF'
from pywebpush import generate_keys
import json

keys = generate_keys()
print(json.dumps(keys, indent=2))
EOF
```

Copy the public and private keys to `.env`.

## Database Queries (SQLite)

```bash
# Connect to database
sqlite3 backend.db

# Useful queries
SELECT * FROM machines;
SELECT * FROM device_secrets;
SELECT * FROM pairing_codes;
SELECT * FROM subscriptions;
SELECT * FROM status_readings ORDER BY received_at DESC LIMIT 10;
SELECT * FROM notification_logs;
SELECT * FROM access_tokens;
```

## Logs and Debugging

```bash
# Check application output
python app.py 2>&1 | tee debug.log

# Flask debug mode
export FLASK_ENV=development
export FLASK_DEBUG=1
python app.py

# Python debugging
python -m pdb app.py  # Step through code
```

## Common Issues

### HMAC Signature Fails (401)
- Device secret doesn't match Pi firmware
- Timestamp on Pi is wrong (check NTP)
- Clock difference > 300 seconds

**Fix:** Sync Pi clock and verify secret:
```bash
python database.py machines  # See registered machines
# Then update secret if needed
python database.py seed hw-000123 "Name" "new-secret"
```

### Bearer Token Invalid (401)
- Token is expired (365-day expiry)
- Token doesn't exist in database
- Wrong SECRET_KEY (app was restarted)

**Fix:** Generate new token via pairing:
```bash
curl -X POST http://localhost:5000/api/v1/pairing/redeem \
  -H "Content-Type: application/json" \
  -d '{"code": "YOUR-CODE"}'
```

### Database Locked
- SQLite has concurrency issues
- Multiple processes accessing simultaneously

**Fix:** Use PostgreSQL for production:
```bash
pip install psycopg2-binary
# Set DATABASE_URL=postgresql://user:pass@localhost/db
```

## Deployment (PythonAnywhere)

```bash
# On your local machine
git add .
git commit -m "Initial Flask backend"
git push origin main

# On PythonAnywhere bash console
cd /home/username
git clone https://github.com/yourusername/repo.git mysite
cd mysite
mkvirtualenv --python=/usr/bin/python3.9 mysite
pip install -r requirements.txt
cp .env.example .env
# Edit .env with production secrets
python database.py init
python database.py seed hw-000123 "Name" "secret"
```

Then configure WSGI file in PythonAnywhere web settings.

## File Structure Reference

```
flask_backend/
├── app.py                # All 7 endpoints
├── config.py             # Configuration & thresholds
├── models.py             # Database models
├── auth.py               # HMAC & JWT
├── state_machine.py      # State transitions
├── push_notifications.py # Web Push
├── database.py           # Management CLI
├── wsgi.py               # Production entry
├── requirements.txt      # Dependencies
├── .env.example          # Config template
├── README.md             # Setup & usage
├── PYTHONANYWHERE_DEPLOYMENT.md
├── IMPLEMENTATION_SUMMARY.md
├── test_api.py           # Tests
└── setup.sh              # Quick setup
```

## Useful Python Commands

```bash
# Generate random SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"

# Check Python version
python3 --version

# List installed packages
pip list

# Freeze dependencies
pip freeze > requirements.txt

# Run Python interactive shell
python3
```

## Environment Variables Checklist

```
✓ SECRET_KEY               - Random string
✓ DATABASE_URL             - sqlite:// or postgresql://
✓ VAPID_PUBLIC_KEY         - Unpadded base64url
✓ VAPID_PRIVATE_KEY        - Keep secret!
✓ VAPID_ADMIN_EMAIL        - Your email
✓ FRONTEND_ORIGIN          - Your app's domain
✓ FLASK_ENV                - development or production
✓ FLASK_DEBUG              - False in production
```

## Performance Tips

```bash
# Production: Use gunicorn with workers
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Adjust workers based on machine: 2 * CPU_cores + 1
# E.g., 4 CPU cores = 9 workers

# For very high load, consider Uvicorn + async:
uvicorn app:app --workers 8
```

## More Help

- 📖 See `README.md` for full API documentation
- 🚀 See `PYTHONANYWHERE_DEPLOYMENT.md` for production setup
- 📋 See `IMPLEMENTATION_SUMMARY.md` for architecture overview
- 🧪 See `test_api.py` for example API calls
