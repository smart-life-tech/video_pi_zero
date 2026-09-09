#!/bin/bash
# Quick setup script for Flask backend development

set -e  # Exit on error

echo "🚀 Flask Backend Setup Script"
echo "=============================="
echo ""

# Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | grep -oE "[0-9]+\.[0-9]+")
echo "✓ Python $PYTHON_VERSION detected"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Upgrade pip
echo "📦 Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env file..."
    cp .env.example .env
    
    # Generate SECRET_KEY
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    sed -i "s/your-super-secret-key-change-this/$SECRET_KEY/" .env
    
    echo "⚠️  Please edit .env file and set:"
    echo "   - VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY"
    echo "   - FRONTEND_ORIGIN"
else
    echo "✓ .env file already exists"
fi

# Initialize database
echo "🗄️  Initializing database..."
python database.py init

# Add test machine
echo "🎯 Adding test machine..."
python database.py seed hw-000123 "Test Machine" "super-secret-key"

# Generate pairing codes
echo "🔑 Generating pairing codes..."
python database.py codes hw-000123 3

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env and set VAPID keys:"
echo "   python3 -c \"from pywebpush import generate_keys; import json; print(json.dumps(generate_keys(), indent=2))\""
echo "2. Run the server:"
echo "   python app.py"
echo "3. Test the API:"
echo "   curl http://localhost:5000/api/v1/push/vapid-public-key"
echo ""
echo "See README.md for more details."
