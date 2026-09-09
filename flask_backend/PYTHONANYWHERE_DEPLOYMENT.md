# PythonAnywhere Deployment Guide

Complete step-by-step guide to deploy the Flask backend to PythonAnywhere.

## Prerequisites

- PythonAnywhere account (free or paid)
- GitHub repository with your Flask backend code (or upload directly)
- VAPID keys for Web Push (generated during setup)
- At least one Raspberry Pi machine to test with

## Step 1: Create Web App on PythonAnywhere

1. Log in to [pythonanywhere.com](https://www.pythonanywhere.com/)
2. Click "Web" in the top menu
3. Click "Add a new web app"
4. Choose domain name (e.g., `username.pythonanywhere.com`)
5. Select **Flask** and **Python 3.9+** (or higher)
6. Finish the wizard

## Step 2: Upload Your Code

### Option A: From Git (Recommended)

```bash
# In PythonAnywhere Bash Console
cd /home/username
git clone https://github.com/yourusername/your-repo.git mysite
cd mysite
```

### Option B: Upload Files Directly

Use the PythonAnywhere file browser to upload your `flask_backend` folder.

## Step 3: Configure Virtual Environment

1. In PythonAnywhere Web console, go to your web app
2. Under "Virtualenv", create a new one pointing to Python 3.9
3. Or in bash:

```bash
cd /home/username/mysite
mkvirtualenv --python=/usr/bin/python3.9 mysite
pip install -r requirements.txt
```

4. Back in Web settings, set the virtualenv path to `/home/username/.virtualenvs/mysite`

## Step 4: Create and Configure .env File

In PythonAnywhere bash:

```bash
cd /home/username/mysite
cp .env.example .env
nano .env
```

**Edit these values:**

```
FLASK_ENV=production
SECRET_KEY=<generate-random-string-here>
DATABASE_URL=sqlite:////home/username/mysite/backend.db
FRONTEND_ORIGIN=https://yourdomain.com
VAPID_PUBLIC_KEY=<your-public-key>
VAPID_PRIVATE_KEY=<your-private-key>
VAPID_ADMIN_EMAIL=your-email@example.com
```

To generate `SECRET_KEY`:
```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

To generate VAPID keys:
```bash
python3 -c "from pywebpush import generate_keys; import json; print(json.dumps(generate_keys(), indent=2))"
```

## Step 5: Initialize Database

```bash
cd /home/username/mysite
workon mysite
python database.py init
```

## Step 6: Add Test Machine

```bash
python database.py seed hw-000123 "Test Machine" "your-shared-secret-here"
```

This secret must match what's in your Raspberry Pi firmware.

## Step 7: Generate Pairing Codes

```bash
python database.py codes hw-000123 5
```

Keep these codes to test with the app.

## Step 8: Configure WSGI File

1. In PythonAnywhere Web settings, click on the WSGI file
2. Edit it to look like this:

```python
import sys
import os

# Add your project to the path
path = '/home/username/mysite'
if path not in sys.path:
    sys.path.append(path)

# Load environment variables
from dotenv import load_dotenv
load_dotenv(os.path.join(path, '.env'))

# Import and create app
from app import create_app
application = create_app()
```

Save the file.

## Step 9: Configure Web App Settings

In PythonAnywhere Web settings:

- **Virtualenv**: `/home/username/.virtualenvs/mysite`
- **WSGI configuration file**: `/var/www/username_pythonanywhere_com_wsgi.py`
- **Python version**: 3.9 (or higher)

Under "Web app setup":
- Leave defaults unless you have specific requirements

## Step 10: Reload and Test

1. Click **Reload** button in Web settings
2. Visit your URL: `https://username.pythonanywhere.com/api/v1/push/vapid-public-key`
3. You should see JSON: `{"publicKey": "..."}`

## Step 11: Test the Full API

### Test Pairing

```bash
curl -X POST https://username.pythonanywhere.com/api/v1/pairing/redeem \
  -H "Content-Type: application/json" \
  -d '{"code": "GEN4821"}'
```

Expected response:
```json
{
  "machineId": "hw-000123",
  "name": "Test Machine",
  "accessToken": "eyJ0eXAi..."
}
```

### Test Status Endpoint

```bash
ACCESS_TOKEN="<token from pairing above>"

curl -X GET https://username.pythonanywhere.com/api/v1/machines/hw-000123/status \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

### Test Pi Ingest

See the testing section in `README.md` for full HMAC signing example.

## Step 12: Set API URL in App

In your frontend build, set the API base URL to:

```
https://username.pythonanywhere.com
```

The app will call:
- `https://username.pythonanywhere.com/api/v1/pairing/redeem`
- `https://username.pythonanywhere.com/api/v1/machines/{id}/status`
- etc.

## Updating Code

When you update your code on GitHub:

```bash
cd /home/username/mysite
git pull
workon mysite
pip install -r requirements.txt
```

Then click **Reload** in PythonAnywhere Web settings.

## Database Backups

Your SQLite database is at:
```
/home/username/mysite/backend.db
```

**Important**: Back this up regularly!

```bash
# Download via PythonAnywhere file browser, or:
cp /home/username/mysite/backend.db /home/username/mysite/backend.db.backup
```

## Switching to PostgreSQL (Production)

For higher scale, use PostgreSQL instead of SQLite:

1. PythonAnywhere offers PostgreSQL databases (paid plans)
2. Install driver: `pip install psycopg2-binary`
3. Set `DATABASE_URL=postgresql://user:password@host/dbname`
4. Reload web app

## Monitoring and Logs

View error logs:
1. In Web settings, scroll to "Log files"
2. Click on "Error log"
3. Or in bash: `tail -f /var/log/username_pythonanywhere_com_error.log`

## Troubleshooting

### 502 Bad Gateway

- Check error log (usually syntax error in code)
- Verify virtualenv path is correct
- Try reloading

### Database locked

- SQLite has issues with concurrent writes
- Consider switching to PostgreSQL
- Or use a larger timeout in config

### Signature verification failures

- Device secret doesn't match Pi's firmware
- Clock on Pi is out of sync (NTP issue)
- Check `X-HW-Timestamp` vs server time

### Module not found errors

- Verify all requirements.txt packages are installed
- Check virtualenv is activated in WSGI file

## Scaling Up

As you add more machines:

1. **Database**: Move from SQLite to PostgreSQL
2. **App processes**: Increase worker count in WSGI
3. **Caching**: Add Redis for session caching
4. **CDN**: Use Cloudflare for static assets

## Security Checklist

- [ ] Change `SECRET_KEY` to a random value
- [ ] Set `FLASK_DEBUG=False`
- [ ] Use HTTPS only (PythonAnywhere provides this)
- [ ] Keep `VAPID_PRIVATE_KEY` secure (environment variable only)
- [ ] Rotate device secrets periodically
- [ ] Enable access logs and review them
- [ ] Set strong passwords for admin/database access

## Next Steps

1. Connect your Raspberry Pi to post readings
2. Test the app with real data
3. Generate and attach pairing codes to machines
4. Monitor logs and notifications

For questions or issues, check:
- [Flask docs](https://flask.palletsprojects.com/)
- [PythonAnywhere docs](https://www.pythonanywhere.com/help/)
- [API Contract](../BACKEND_CONTRACT.md)
