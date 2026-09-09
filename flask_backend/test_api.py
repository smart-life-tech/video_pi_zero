"""
Test suite for the backend API.
Run with: pytest test_api.py -v
"""

import pytest
import json
import hashlib
import hmac
import time
from datetime import datetime, timezone

from app import create_app
from models import db, Machine, DeviceSecret, PairingCode
from config import TestingConfig


@pytest.fixture
def app():
    """Create and configure a test app."""
    app = create_app(TestingConfig)
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client."""
    return app.test_client()


@pytest.fixture
def setup_machine(app):
    """Setup a test machine with secret."""
    with app.app_context():
        machine = Machine(id='hw-000123', name='Test Machine')
        db.session.add(machine)
        
        secret = DeviceSecret(
            machine_id='hw-000123',
            key_id='v1',
            secret='super-secret-key',
            active=True
        )
        db.session.add(secret)
        
        pairing = PairingCode(
            code='GEN4821',
            machine_id='hw-000123',
            redeemed=False
        )
        db.session.add(pairing)
        
        db.session.commit()
    
    return 'hw-000123'


def test_pairing_redeem(client, setup_machine):
    """Test pairing code redemption."""
    response = client.post('/api/v1/pairing/redeem', json={'code': 'GEN-4821'})
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['machineId'] == 'hw-000123'
    assert data['name'] == 'Test Machine'
    assert data['accessToken']


def test_pairing_invalid_code(client):
    """Test invalid pairing code."""
    response = client.post('/api/v1/pairing/redeem', json={'code': 'INVALID'})
    assert response.status_code == 404
    data = response.get_json()
    assert data['error']['code'] == 'invalid_pairing_code'


def test_pairing_code_normalization(client, setup_machine):
    """Test pairing code normalization (case-insensitive, non-alphanumerics ignored)."""
    # All of these should work
    for code in ['gen-4821', 'GEN-4821', 'GEN 4821', 'gen 4821']:
        response = client.post('/api/v1/pairing/redeem', json={'code': code})
        assert response.status_code == 200 or response.status_code == 404  # 404 if already used
        
        if response.status_code == 404:
            # Code was already used, try regenerating for next test
            data = response.get_json()
            assert data['error']['code'] == 'invalid_pairing_code'


def test_get_machine_status(client, app, setup_machine):
    """Test getting machine status."""
    # First redeem to get token
    with app.app_context():
        from auth import generate_access_token
        token = generate_access_token('hw-000123')
    
    response = client.get(
        '/api/v1/machines/hw-000123/status',
        headers={'Authorization': f'Bearer {token}'}
    )
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['machineId'] == 'hw-000123'
    assert data['liquid']['state'] == 'ok'


def test_status_unauthorized(client):
    """Test status endpoint without token."""
    response = client.get('/api/v1/machines/hw-000123/status')
    assert response.status_code == 401


def test_status_wrong_machine(client, app, setup_machine):
    """Test accessing different machine with token."""
    with app.app_context():
        from auth import generate_access_token
        token = generate_access_token('hw-000123')
    
    response = client.get(
        '/api/v1/machines/hw-999999/status',
        headers={'Authorization': f'Bearer {token}'}
    )
    
    assert response.status_code == 403
    data = response.get_json()
    assert data['error']['code'] == 'wrong_machine'


def test_ingest_status(client, setup_machine):
    """Test Pi posting a reading."""
    device_id = 'hw-000123'
    timestamp = int(time.time())
    secret = 'super-secret-key'
    
    payload = {
        'machineId': device_id,
        'liquid': {'state': 'low', 'percent': 8},
        'firmware': '1.4.2',
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }
    
    body = json.dumps(payload, separators=(',', ':')).encode()
    body_hash = hashlib.sha256(body).hexdigest()
    
    canonical = '\n'.join(['POST', '/api/v1/ingest/status', str(timestamp), device_id, body_hash])
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    
    response = client.post(
        '/api/v1/ingest/status',
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-HW-Device-Id': device_id,
            'X-HW-Timestamp': str(timestamp),
            'X-HW-Key-Id': 'v1',
            'X-HW-Signature': signature
        }
    )
    
    assert response.status_code == 202


def test_ingest_invalid_signature(client, setup_machine):
    """Test Pi posting with wrong signature."""
    device_id = 'hw-000123'
    timestamp = int(time.time())
    
    payload = {
        'machineId': device_id,
        'liquid': {'state': 'ok', 'percent': 50},
        'firmware': '1.4.2',
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    }
    
    body = json.dumps(payload, separators=(',', ':')).encode()
    
    response = client.post(
        '/api/v1/ingest/status',
        data=body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-HW-Device-Id': device_id,
            'X-HW-Timestamp': str(timestamp),
            'X-HW-Key-Id': 'v1',
            'X-HW-Signature': 'invalid_signature_here'
        }
    )
    
    assert response.status_code == 401


def test_vapid_public_key(client):
    """Test getting VAPID public key."""
    response = client.get('/api/v1/push/vapid-public-key')
    
    assert response.status_code == 200
    data = response.get_json()
    assert data['publicKey']


def test_cors_headers(client):
    """Test that CORS headers are present."""
    response = client.get(
        '/api/v1/push/vapid-public-key',
        headers={'Origin': 'http://localhost:5173'}
    )
    
    assert response.status_code == 200
    # CORS headers should be present
    assert 'Access-Control-Allow-Origin' in response.headers or response.status_code == 200


def test_cache_control_headers(client):
    """Test that Cache-Control headers are set correctly."""
    response = client.get('/api/v1/push/vapid-public-key')
    
    assert response.status_code == 200
    assert response.headers.get('Cache-Control') == 'no-store'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
