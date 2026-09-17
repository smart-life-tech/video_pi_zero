"""Focused contract tests for security, timestamps, and state transitions."""

import hashlib
import hmac
import json
import time
from datetime import datetime, timezone

import pytest

from app import create_app
from config import TestingConfig
from models import db, DeviceSecret, Machine, PairingCode, StatusReading
from state_machine import StateManager


@pytest.fixture
def app():
    application = create_app(TestingConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def add_machine(app):
    with app.app_context():
        db.session.add(Machine(id='hw-000123', name='Test Machine'))
        db.session.add(DeviceSecret(machine_id='hw-000123', key_id='v1', secret='secret'))
        db.session.commit()


def signed_request(client, payload, body=None, timestamp=None):
    device_id = 'hw-000123'
    timestamp = timestamp or str(int(time.time()))
    raw_body = body or json.dumps(payload, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw_body).hexdigest()
    canonical = '\n'.join(['POST', '/api/v1/ingest/status', timestamp, device_id, digest])
    signature = hmac.new(b'secret', canonical.encode(), hashlib.sha256).hexdigest()
    response = client.post(
        '/api/v1/ingest/status',
        data=raw_body,
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'X-HW-Device-Id': device_id,
            'X-HW-Timestamp': timestamp,
            'X-HW-Key-Id': 'v1',
            'X-HW-Signature': signature,
        },
    )
    return response, timestamp


def reading_payload(percent=60, state='ok'):
    return {
        'machineId': 'hw-000123',
        'liquid': {'state': state, 'percent': percent},
        'firmware': '1.0.0',
        'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def test_ingest_accepts_and_rejects_exact_duplicate(client, app):
    add_machine(app)
    payload = reading_payload()
    response, timestamp = signed_request(client, payload)
    assert response.status_code == 202
    duplicate, _ = signed_request(
        client,
        payload,
        json.dumps(payload, separators=(',', ':')).encode(),
        timestamp=timestamp,
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()['error']['code'] == 'duplicate_request'


def test_ingest_rejects_invalid_timestamp(client, app):
    add_machine(app)
    payload = reading_payload()
    payload['ts'] = '2026-09-17T12:00:00+00:00'
    response, _ = signed_request(client, payload)
    assert response.status_code == 422
    assert response.get_json()['error']['code'] == 'invalid_request'


def test_state_transition_requires_three_readings(app):
    with app.app_context():
        machine = Machine(id='hw-000123', name='Test Machine')
        db.session.add(machine)
        db.session.flush()
        manager = StateManager(db)
        for percent in (40, 40):
            reading = StatusReading(machine_id=machine.id, state='ok', percent=percent)
            db.session.add(reading)
            manager.process_reading(machine, reading)
            assert machine.state == 'ok'
        reading = StatusReading(machine_id=machine.id, state='ok', percent=40)
        db.session.add(reading)
        manager.process_reading(machine, reading)
        assert machine.state == 'warn'
