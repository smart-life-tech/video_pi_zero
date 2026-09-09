"""Authentication and authorization utilities."""

import hashlib
import hmac
import secrets
import jwt
from datetime import datetime, timedelta, timezone
from typing import Tuple
from config import Config
from models import db, DeviceSecret, AccessToken
import logging

logger = logging.getLogger(__name__)


def verify_hmac_signature(
    device_id: str,
    timestamp: int,
    raw_body: bytes,
    provided_signature: str,
    key_id: str
) -> Tuple[bool, str]:
    """
    Verify HMAC-SHA256 signature from Pi.
    
    Signature is computed over:
    POST
    /api/v1/ingest/status
    <timestamp>
    <device_id>
    <sha256 of raw body>
    
    Args:
        device_id: Machine ID (hw-000123)
        timestamp: Unix seconds when request was signed
        raw_body: Raw JSON bytes that were signed
        provided_signature: Hex signature from header
        key_id: Which key version was used
    
    Returns:
        (is_valid, error_message)
    """
    from config import Config
    import time
    
    # Check timestamp is within tolerance (5 minutes = 300 seconds)
    current_ts = int(time.time())
    time_diff = abs(current_ts - timestamp)
    
    if time_diff > Config.TIMESTAMP_TOLERANCE:
        return False, f'Timestamp too far off: {time_diff}s difference'
    
    # Get the device secret
    secret = DeviceSecret.query.filter_by(
        machine_id=device_id,
        key_id=key_id,
        active=True
    ).first()
    
    if not secret:
        return False, f'No secret found for {device_id}/{key_id}'
    
    # Compute the canonical message
    body_hash = hashlib.sha256(raw_body).hexdigest()
    canonical = '\n'.join([
        'POST',
        '/api/v1/ingest/status',
        str(timestamp),
        device_id,
        body_hash
    ])
    
    # Compute expected signature
    expected = hmac.new(
        secret.secret.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Compare (constant-time to prevent timing attacks)
    is_valid = hmac.compare_digest(expected, provided_signature)
    
    if not is_valid:
        logger.warning(f'Signature mismatch for {device_id}/{key_id}')
        return False, 'Invalid signature'
    
    return True, 'OK'


def generate_access_token(machine_id: str) -> str:
    """
    Generate a JWT access token for a machine.
    Token is used by the app in Bearer authentication.
    
    Returns: token string
    """
    # Create token in database for tracking
    token_value = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=365)
    
    access_token = AccessToken(
        machine_id=machine_id,
        token=token_value,
        expires_at=expires_at
    )
    
    db.session.add(access_token)
    db.session.flush()  # Get the token object created
    
    # Create JWT payload
    payload = {
        'sub': machine_id,  # Machine ID as subject
        'jti': access_token.id,  # Token ID in database
        'iat': datetime.now(timezone.utc),
        'exp': expires_at
    }
    
    # Encode JWT
    token = jwt.encode(
        payload,
        Config.SECRET_KEY,
        algorithm='HS256'
    )
    
    return token


def decode_access_token(token: str):
    """
    Decode and verify a JWT access token.
    
    Returns: machine_id if valid, None if invalid/expired
    """
    try:
        payload = jwt.decode(
            token,
            Config.SECRET_KEY,
            algorithms=['HS256']
        )
        machine_id = payload.get('sub')
        jti = payload.get('jti')
        
        # Verify token exists in database and is still valid
        access_token = AccessToken.query.filter_by(
            id=jti,
            machine_id=machine_id
        ).first()
        
        if not access_token or not access_token.is_valid():
            return None
        
        # Update last used
        access_token.last_used_at = datetime.now(timezone.utc)
        db.session.commit()
        
        return machine_id
        
    except jwt.InvalidTokenError as e:
        logger.warning(f'Invalid token: {e}')
        return None
    except Exception as e:
        logger.error(f'Error decoding token: {e}')
        return None


def add_device_secret(machine_id: str, key_id: str, secret: str) -> DeviceSecret:
    """
    Add a device secret for a machine.
    Used during provisioning.
    
    Args:
        machine_id: hw-000123
        key_id: v1, v2, etc.
        secret: Raw shared secret (must match Pi's firmware)
    
    Returns: DeviceSecret object
    """
    # Deactivate other keys with same ID (key rotation)
    DeviceSecret.query.filter_by(
        machine_id=machine_id,
        key_id=key_id
    ).update({'active': False})
    
    device_secret = DeviceSecret(
        machine_id=machine_id,
        key_id=key_id,
        secret=secret,
        active=True,
        rotated_at=datetime.now(timezone.utc)
    )
    
    db.session.add(device_secret)
    return device_secret


# Test vectors from contract section 7.6
# These match the reference implementation
if __name__ == '__main__':
    """Test HMAC signing against contract test vectors."""
    
    # Test vector from contract
    device_id = 'hw-000123'
    timestamp = 1788255242
    key = 'super-secret-key'
    body = b'{"machineId":"hw-000123","liquid":{"state":"low","percent":8},"firmware":"1.4.2","ts":"2026-08-31T09:14:02Z"}'
    
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f'POST\n/api/v1/ingest/status\n{timestamp}\n{device_id}\n{body_hash}'
    
    expected_sig = hmac.new(
        key.encode(),
        canonical.encode(),
        hashlib.sha256
    ).hexdigest()
    
    print(f'Body hash: {body_hash}')
    print(f'Canonical:\n{canonical}')
    print(f'Expected signature: {expected_sig}')
    print()
    print('If this matches the contract test vector, HMAC is correctly implemented.')
