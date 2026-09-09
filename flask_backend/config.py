"""Configuration for Flask backend."""

import os
from datetime import timedelta

class Config:
    """Base configuration."""
    
    # Flask
    DEBUG = os.environ.get('FLASK_DEBUG', 'False') == 'True'
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///backend.db'  # SQLite for development/small deployment
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # CORS - Update with your frontend origin
    CORS_ORIGINS = [
        'http://localhost:5173',           # Vite dev server
        'http://localhost:3000',           # Alternative dev
        'http://127.0.0.1:5173',
        'http://127.0.0.1:3000',
        os.environ.get('FRONTEND_ORIGIN', ''),  # Production origin
    ]
    CORS_ORIGINS = [o for o in CORS_ORIGINS if o]  # Remove empty strings
    
    # Push Notifications (Web Push / VAPID)
    # Generate with: from pywebpush import generate_keys; generate_keys()
    VAPID_PUBLIC_KEY = os.environ.get(
        'VAPID_PUBLIC_KEY',
        'BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U'
    )
    VAPID_PRIVATE_KEY = os.environ.get('VAPID_PRIVATE_KEY', '')
    VAPID_ADMIN_EMAIL = os.environ.get('VAPID_ADMIN_EMAIL', 'admin@example.com')
    
    # Device secrets (for HMAC signing)
    # Map device_id -> {key_id -> secret}
    # In production, load from database or secure config
    DEVICE_SECRETS = {}
    
    # State machine thresholds (from contract section 8.2)
    STATE_THRESHOLDS = {
        'ok_to_warn': 40,      # percent <= 40 enters warn
        'warn_to_low': 10,     # percent <= 10 with state=low enters low
        'low_to_warn': 20,     # percent >= 20 leaves low
        'warn_to_ok': 50,      # percent >= 50 with state=ok returns to ok
        'consecutive_readings': 3  # Require 3 consecutive readings for state change
    }
    
    # Rate limiting
    RATE_LIMITS = {
        'redeem': '5/hour',
        'status': '300/hour',
        'ingest': '300/hour'  # 1 per 5 minutes = ~288 per day < 300/hour
    }
    
    # Timestamp tolerance (5 minutes = 300 seconds)
    TIMESTAMP_TOLERANCE = 300
    
    # Push notification settings
    PUSH_SETTINGS = {
        'retry_after_seconds': 3600,  # 1 hour retry for failed pushes
        'max_retries': 3,
        'min_notification_interval': 43200,  # 12 hours between reminders
    }


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration (PythonAnywhere, etc)."""
    DEBUG = False
    TESTING = False
    
    # In production, these MUST be set via environment variables
    assert os.environ.get('SECRET_KEY'), 'SECRET_KEY must be set in production'
    assert os.environ.get('VAPID_PRIVATE_KEY'), 'VAPID_PRIVATE_KEY must be set in production'


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False
