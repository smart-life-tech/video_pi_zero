# Flask Backend - Complete Index

## 📦 What You've Got

A production-ready Flask backend with **all 7 API endpoints** from the contract, ready to deploy to PythonAnywhere.

## 🚀 Start Here

1. **First time?** Read [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) (5 min overview)
2. **Want quick setup?** Run `./setup.sh` then read [QUICK_REFERENCE.md](QUICK_REFERENCE.md)
3. **Deploying to PythonAnywhere?** Follow [PYTHONANYWHERE_DEPLOYMENT.md](PYTHONANYWHERE_DEPLOYMENT.md) step-by-step
4. **Need API details?** See [README.md](README.md)

## 📚 Documentation Files

| File | Purpose |
|------|---------|
| **IMPLEMENTATION_SUMMARY.md** | Architecture overview, features, what was built (read this first) |
| **PYTHONANYWHERE_DEPLOYMENT.md** | Complete step-by-step PythonAnywhere setup |
| **README.md** | API endpoints, configuration, testing, troubleshooting |
| **QUICK_REFERENCE.md** | Common commands, cURL examples, quick lookup |
| **This file** | Navigation and file listing |

## 🔧 Application Files

| File | Purpose |
|------|---------|
| **app.py** | Main Flask app with all 7 endpoints (700 lines) |
| **config.py** | Environment configuration, thresholds |
| **models.py** | Database schema (7 tables) |
| **auth.py** | HMAC verification & JWT tokens |
| **state_machine.py** | Liquid level state transitions (ok/warn/low) |
| **push_notifications.py** | Web Push notification handling |
| **database.py** | CLI for database management |
| **wsgi.py** | Production WSGI entry point |

## 🔑 Configuration Files

| File | Purpose |
|------|---------|
| **.env.example** | Template for environment variables |
| **.gitignore** | Git ignore rules |
| **requirements.txt** | Python dependencies (9 packages) |

## 🧪 Testing

| File | Purpose |
|------|---------|
| **test_api.py** | Pytest test suite (12 tests) |

## 📋 Setup Scripts

| File | Purpose |
|------|---------|
| **setup.sh** | One-command local development setup |

## 🏗️ Architecture

```
User's Phone (App)          Raspberry Pi in Machine
        │                           │
        ├──── (bearer token) ────────────────┐
        │                                    │
        ├──── GET /machines/{id}/status ────┤
        │                                    │
        └───── POST /push/subscriptions     │
                                            │
                    (HMAC-signed)           │
                                      (every 5 min)
                                            │
                    Flask Backend ◄─────────┘
                    (PythonAnywhere)
                    
    Stores state, tracks notifications, decides ok/warn/low
```

## 🎯 The 7 Endpoints

```
POST   /api/v1/pairing/redeem              → Get access token
GET    /api/v1/machines/{id}/status        → Poll machine state
GET    /api/v1/push/vapid-public-key       → Get Web Push key
POST   /api/v1/push/subscriptions          → Register for notifications
DELETE /api/v1/push/subscriptions          → Unregister
POST   /api/v1/ingest/status               ← Pi posts reading (HMAC-signed)
GET    /api/v1/machines/{id}/stream        → Optional SSE (returns 404)
```

## 📊 Database Tables

1. **machines** - Device definitions (hw-000123)
2. **status_readings** - Individual Pi readings
3. **pairing_codes** - Single-use codes (printed on sticker)
4. **device_secrets** - Shared secrets for HMAC (supports key rotation)
5. **subscriptions** - Push notification endpoints (idempotent)
6. **access_tokens** - JWT tokens for Bearer auth
7. **notification_logs** - Audit trail of notifications

## ✨ Key Features

✅ HMAC-SHA256 signature verification for Pi  
✅ JWT Bearer tokens for app authentication  
✅ State machine: ok → warn → low (anti-flapping)  
✅ Idempotent push subscriptions (no duplicates)  
✅ Key rotation support  
✅ CORS for frontend cross-domain  
✅ Standard error format  
✅ Comprehensive logging  
✅ Full test suite  
✅ Production-ready (gunicorn, PostgreSQL support)  

## 🚀 Quick Start

### Local Development

```bash
# One command setup
./setup.sh

# Run server
python app.py

# Test
curl http://localhost:5000/api/v1/push/vapid-public-key
```

### Production (PythonAnywhere)

1. Follow [PYTHONANYWHERE_DEPLOYMENT.md](PYTHONANYWHERE_DEPLOYMENT.md)
2. Deploy in ~15 minutes
3. Get live URL like `https://username.pythonanywhere.com`

## 📝 Configuration

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

Edit these:
- `SECRET_KEY` - Generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY` - Generate via `pywebpush`
- `FRONTEND_ORIGIN` - Your app's domain
- `DATABASE_URL` - sqlite:///backend.db or postgresql://...

## 🗄️ Database Management

```bash
python database.py init                    # Create tables
python database.py seed hw-000123 "Name" "secret"  # Add machine
python database.py codes hw-000123 5       # Generate pairing codes
python database.py machines                # List all
```

## 🧪 Testing

```bash
pytest test_api.py -v          # Run all tests
pytest test_api.py::test_pairing_redeem -v  # One test
```

## 📖 Next Steps

1. **Read** [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - Understand what was built
2. **Setup locally** - Run `./setup.sh`
3. **Test locally** - `python app.py` then curl endpoints
4. **Deploy** - Follow [PYTHONANYWHERE_DEPLOYMENT.md](PYTHONANYWHERE_DEPLOYMENT.md)
5. **Connect Pi** - Get firmware to POST to `/api/v1/ingest/status`
6. **Build frontend** - Point app's API base URL to your backend

## 🔍 Common Commands

```bash
# Database setup
python database.py init
python database.py seed hw-000123 "Test Machine" "shared-secret"
python database.py codes hw-000123 5

# Local development
python app.py                   # Development server
python app.py 2>&1 | tee debug.log  # With logging

# Production
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Testing
pytest test_api.py -v

# Configuration
nano .env                       # Edit settings
python3 -c "from pywebpush import generate_keys; import json; print(json.dumps(generate_keys(), indent=2))"  # VAPID keys
```

See [QUICK_REFERENCE.md](QUICK_REFERENCE.md) for more commands.

## 📚 Reference Documents

- 📖 [API Contract](../BACKEND_CONTRACT.md) - Full specification from client
- 🔑 [Auth Logic](./auth.py) - HMAC signing and JWT verification
- 🎯 [State Machine](./state_machine.py) - Level classification logic
- 🔔 [Push Logic](./push_notifications.py) - Notification handling

## 💡 Pro Tips

- Start local with `./setup.sh` and `python app.py`
- Test all endpoints with curl before deploying (examples in README.md)
- Generate VAPID keys once, reuse across environments
- Use SQLite for dev/testing, PostgreSQL for production
- Enable error logging to monitor issues on PythonAnywhere
- Back up database regularly!

## ⚙️ Customization

All thresholds are in `config.py`:

```python
STATE_THRESHOLDS = {
    'ok_to_warn': 40,           # Adjust based on your tank
    'warn_to_low': 10,
    'low_to_warn': 20,
    'warn_to_ok': 50,
    'consecutive_readings': 3   # Anti-flapping count
}
```

## 🆘 Troubleshooting

- **Pi signature fails?** Device secret doesn't match. Check with `python database.py machines`
- **No notifications?** Verify VAPID keys are set. Check notification_logs table.
- **Database locked?** Switch to PostgreSQL for production.
- **CORS errors?** Update FRONTEND_ORIGIN in .env

See [README.md](README.md#troubleshooting) for detailed troubleshooting.

## ✅ Deployment Checklist

- [ ] Read IMPLEMENTATION_SUMMARY.md
- [ ] Run ./setup.sh locally
- [ ] Test with curl examples from QUICK_REFERENCE.md
- [ ] Generate SECRET_KEY
- [ ] Generate VAPID keys
- [ ] Add test machine with database.py
- [ ] Generate pairing codes
- [ ] Follow PYTHONANYWHERE_DEPLOYMENT.md
- [ ] Test live endpoints
- [ ] Set frontend CORS origin
- [ ] Deploy frontend pointing to backend

---

**Everything is ready!** Start with [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) and you'll be live in less than an hour.
