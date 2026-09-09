"""Database models for the backend."""

from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone, timedelta
import uuid

db = SQLAlchemy()


class Machine(db.Model):
    """Physical machine in the field."""
    __tablename__ = 'machines'
    
    id = db.Column(db.String(20), primary_key=True)  # hw-000123
    name = db.Column(db.String(255), nullable=False)
    
    # Confirmed state (ok, warn, low)
    state = db.Column(db.String(10), default='ok', nullable=False)
    state_updated_at = db.Column(db.DateTime, default=datetime.now)
    
    # When it was last seen
    last_reading_at = db.Column(db.DateTime)
    
    # Last confirmed percent (for UI)
    last_confirmed_percent = db.Column(db.Integer)
    
    # Notification state tracking
    last_notification_at = db.Column(db.DateTime)  # Last time we notified about this state
    consecutive_low_readings = db.Column(db.Integer, default=0)  # Count for state transitions
    
    # Relationships
    readings = db.relationship('StatusReading', backref='machine', lazy=True, cascade='all, delete-orphan')
    subscriptions = db.relationship('Subscription', backref='machine', lazy=True, cascade='all, delete-orphan')
    secrets = db.relationship('DeviceSecret', backref='machine', lazy=True, cascade='all, delete-orphan')
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    def get_confirmed_state(self):
        """Return the current confirmed state with percent."""
        return {
            'state': self.state,
            'percent': self.last_confirmed_percent,
            'percentAvailable': self.last_confirmed_percent is not None
        }
    
    def __repr__(self):
        return f'<Machine {self.id}>'


class StatusReading(db.Model):
    """Individual reading from a machine."""
    __tablename__ = 'status_readings'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    machine_id = db.Column(db.String(20), db.ForeignKey('machines.id'), nullable=False)
    
    # From the Pi's reading
    state = db.Column(db.String(10), nullable=False)  # 'ok' or 'low'
    percent = db.Column(db.Integer)  # 0-100 or None
    firmware = db.Column(db.String(50))
    
    # Timestamp from the Pi
    pi_timestamp = db.Column(db.DateTime)
    
    # When we received it
    received_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<Reading {self.machine_id} {self.state} {self.percent}%>'


class PairingCode(db.Model):
    """One-time pairing codes for machines."""
    __tablename__ = 'pairing_codes'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    code = db.Column(db.String(20), unique=True, nullable=False, index=True)  # GEN-4821
    machine_id = db.Column(db.String(20), db.ForeignKey('machines.id'), nullable=False)
    
    redeemed = db.Column(db.Boolean, default=False)
    redeemed_at = db.Column(db.DateTime)
    redeemed_ip = db.Column(db.String(50))  # For audit
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(days=30))
    
    def is_valid(self):
        """Check if code is still valid."""
        if self.redeemed:
            return False
        if datetime.now(timezone.utc) > self.expires_at:
            return False
        return True
    
    def redeem(self, ip_address=None):
        """Mark code as redeemed."""
        self.redeemed = True
        self.redeemed_at = datetime.now(timezone.utc)
        self.redeemed_ip = ip_address
    
    def __repr__(self):
        return f'<PairingCode {self.code} for {self.machine_id}>'


class DeviceSecret(db.Model):
    """Device secrets for HMAC signing."""
    __tablename__ = 'device_secrets'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    machine_id = db.Column(db.String(20), db.ForeignKey('machines.id'), nullable=False, index=True)
    
    key_id = db.Column(db.String(20), nullable=False)  # v1, v2, etc.
    secret = db.Column(db.String(255), nullable=False)  # Shared secret (raw UTF-8)
    
    active = db.Column(db.Boolean, default=True)  # Can rotate keys
    created_at = db.Column(db.DateTime, default=datetime.now)
    rotated_at = db.Column(db.DateTime)
    
    __table_args__ = (
        db.UniqueConstraint('machine_id', 'key_id', name='uq_machine_keyid'),
    )
    
    def __repr__(self):
        return f'<DeviceSecret {self.machine_id}/{self.key_id}>'


class Subscription(db.Model):
    """Push notification subscriptions."""
    __tablename__ = 'subscriptions'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    machine_id = db.Column(db.String(20), db.ForeignKey('machines.id'), nullable=False)
    
    endpoint = db.Column(db.String(500), unique=True, nullable=False, index=True)  # Web Push endpoint
    p256dh = db.Column(db.String(255))  # Public key
    auth = db.Column(db.String(255))    # Auth secret
    
    platform = db.Column(db.String(50), default='other')  # android, ios, desktop, other
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    
    last_push_at = db.Column(db.DateTime)
    failed_pushes = db.Column(db.Integer, default=0)
    
    def __repr__(self):
        return f'<Subscription {self.machine_id} {self.platform}>'


class AccessToken(db.Model):
    """Short-lived access tokens for API calls."""
    __tablename__ = 'access_tokens'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    machine_id = db.Column(db.String(20), db.ForeignKey('machines.id'), nullable=False, index=True)
    
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    expires_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc) + timedelta(days=365))
    
    last_used_at = db.Column(db.DateTime)
    
    def is_valid(self):
        """Check if token is still valid."""
        if datetime.now(timezone.utc) > self.expires_at:
            return False
        return True
    
    def __repr__(self):
        return f'<AccessToken {self.machine_id}>'


class NotificationLog(db.Model):
    """Log of notifications sent for audit and rate limiting."""
    __tablename__ = 'notification_logs'
    
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    machine_id = db.Column(db.String(20), db.ForeignKey('machines.id'), nullable=False, index=True)
    subscription_id = db.Column(db.String(36), db.ForeignKey('subscriptions.id'))
    
    state_change = db.Column(db.String(50))  # 'ok->warn', 'warn->low', etc.
    triggered_by_reading_id = db.Column(db.String(36), db.ForeignKey('status_readings.id'))
    
    sent_at = db.Column(db.DateTime, default=datetime.now)
    status = db.Column(db.String(20), default='pending')  # pending, sent, failed, skipped
    
    created_at = db.Column(db.DateTime, default=datetime.now)
    
    def __repr__(self):
        return f'<NotificationLog {self.machine_id} {self.state_change}>'
