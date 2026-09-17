"""
Flask backend for liquid level monitoring system.
Implements the API contract for machine status, push notifications, and device pairing.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone
import math
import re
import hashlib
import time
from datetime import timedelta
from typing import Optional
from sqlalchemy.exc import IntegrityError
import os
import logging

from config import Config
from models import (
    db, Machine, PairingCode, Subscription, DeviceSecret, StatusReading,
    IngestRequest, RateLimitBucket,
)
from auth import verify_hmac_signature
from state_machine import StateManager
from push_notifications import PushNotificationManager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_app(config_class=Config):
    """Application factory pattern."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    if app.config.get('REQUIRE_PRODUCTION_SETTINGS'):
        if not app.config.get('SECRET_KEY') or not os.environ.get('SECRET_KEY'):
            raise RuntimeError('SECRET_KEY must be set in production')
        if not app.config.get('VAPID_PRIVATE_KEY') or not os.environ.get('VAPID_PRIVATE_KEY'):
            raise RuntimeError('VAPID_PRIVATE_KEY must be set in production')
        database_url = os.environ.get('DATABASE_URL', '')
        if not database_url.startswith(('postgresql://', 'postgresql+psycopg2://')):
            raise RuntimeError('DATABASE_URL must use PostgreSQL in production')
    
    # Initialize extensions
    db.init_app(app)
    CORS(
        app,
        resources={r"/api/*": {
            "origins": config_class.CORS_ORIGINS,
            "expose_headers": ["Retry-After"],
        }},
    )
    
    # Initialize managers
    state_manager = StateManager(db)
    push_manager = PushNotificationManager()
    
    with app.app_context():
        db.create_all()

    @app.after_request
    def apply_response_headers(response):
        response.headers.setdefault('Cache-Control', 'no-store')
        response.headers.setdefault('Access-Control-Expose-Headers', 'Retry-After')
        return response
    
    # ==================== PAIRING ====================
    @app.route('/api/v1/pairing/redeem', methods=['POST'])
    def redeem_pairing_code():
        """
        POST /pairing/redeem
        Owner enters pairing code from machine sticker.
        """
        try:
            data = request.get_json()
            if not data or 'code' not in data:
                return error_response('invalid_pairing_code', 'Code required'), 404
            
            # Normalize code: remove non-alphanumerics, case-insensitive
            raw_code = data['code']
            normalized = ''.join(c.upper() for c in raw_code if c.isalnum())
            
            if not normalized:
                return error_response('invalid_pairing_code', 'Invalid code format'), 404

            client_ip = request.remote_addr or 'unknown'
            for identity in (f'pairing-ip:{client_ip}', f'pairing-code:{normalized}'):
                limited = enforce_rate_limit(identity, limit=5, window_seconds=3600)
                if limited:
                    return limited
            
            pairing = PairingCode.query.filter_by(code=normalized).first()
            
            if not pairing or not pairing.is_valid():
                return error_response('invalid_pairing_code', 'Code not found or expired'), 404
            
            if pairing.redeemed:
                return error_response('invalid_pairing_code', 'Code already used'), 404
            
            # Get or create machine
            machine = Machine.query.get(pairing.machine_id)
            if not machine:
                return error_response('invalid_pairing_code', 'Machine not found'), 404
            
            # Mark code as redeemed
            pairing.redeem()
            db.session.commit()
            
            # Create access token
            from auth import generate_access_token
            access_token = generate_access_token(machine.id)
            
            return jsonify({
                'machineId': machine.id,
                'name': machine.name,
                'accessToken': access_token
            }), 200
        
        except Exception as e:
            logger.error(f"Error redeeming pairing code: {e}")
            return error_response('invalid_pairing_code', 'Invalid code'), 404
    
    # ==================== STATUS ====================
    @app.route('/api/v1/machines/<machine_id>/status', methods=['GET'])
    def get_machine_status(machine_id):
        """
        GET /machines/{machineId}/status
        App polls every 30 seconds for current machine state.
        """
        # Verify Bearer token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return error_response('unauthorized', 'Bearer token required'), 401
        
        token = auth_header[7:]
        resolved_machine_id = verify_access_token(token)
        
        if not resolved_machine_id:
            return error_response('unauthorized', 'Invalid or expired token'), 401
        
        if resolved_machine_id != machine_id:
            return error_response('wrong_machine', 'Token does not match machine'), 403

        limited = enforce_rate_limit(f'status:{resolved_machine_id}', limit=300, window_seconds=3600)
        if limited:
            return limited
        
        machine = Machine.query.get(machine_id)
        if not machine:
            return error_response('machine_not_found', 'Machine not found'), 404
        
        def utc_string(value):
            if value is None:
                return None
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        status_data = {
            'machineId': machine.id,
            'name': machine.name,
            'liquid': machine.get_confirmed_state(),
            'lastSeenAt': utc_string(machine.last_reading_at),
            'updatedAt': utc_string(machine.state_updated_at)
        }
        
        response = jsonify(status_data)
        response.headers['Cache-Control'] = 'no-store'
        return response, 200
    
    # ==================== VAPID PUBLIC KEY ====================
    @app.route('/api/v1/push/vapid-public-key', methods=['GET'])
    def get_vapid_public_key():
        """
        GET /push/vapid-public-key
        Returns the VAPID public key for push subscription.
        """
        response = jsonify({
            'publicKey': Config.VAPID_PUBLIC_KEY
        })
        response.headers['Cache-Control'] = 'no-store'
        return response, 200
    
    # ==================== PUSH SUBSCRIPTIONS ====================
    @app.route('/api/v1/push/subscriptions', methods=['POST'])
    def subscribe_to_push():
        """
        POST /push/subscriptions
        Register a device for push notifications (idempotent).
        """
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return error_response('unauthorized', 'Bearer token required'), 401
        
        token = auth_header[7:]
        machine_id = verify_access_token(token)
        
        if not machine_id:
            return error_response('unauthorized', 'Invalid token'), 401

        limited = enforce_rate_limit(f'push:{machine_id}', limit=300, window_seconds=3600)
        if limited:
            return limited
        
        data = request.get_json()
        if not data or 'subscription' not in data:
            return error_response('invalid_subscription', 'Subscription required'), 400
        
        provided_machine_id = data.get('machineId')
        if provided_machine_id != machine_id:
            return error_response('wrong_machine', 'Token machine mismatch'), 403
        
        subscription = data['subscription']
        endpoint = subscription.get('endpoint')
        keys = subscription.get('keys')
        platform = data.get('platform')
        if (
            not isinstance(endpoint, str)
            or not endpoint.startswith('https://')
            or not isinstance(keys, dict)
            or not isinstance(keys.get('p256dh'), str)
            or not isinstance(keys.get('auth'), str)
            or platform not in {'ios', 'android', 'desktop', 'other'}
        ):
            return error_response('invalid_subscription', 'Invalid subscription'), 400
        
        # Upsert subscription
        sub = Subscription.query.filter_by(endpoint=endpoint).first()
        is_new = sub is None
        
        if is_new:
            sub = Subscription(
                machine_id=machine_id,
                endpoint=endpoint,
                p256dh=keys['p256dh'],
                auth=keys['auth'],
                platform=platform
            )
        else:
            # Update if exists
            sub.machine_id = machine_id
            if sub.machine_id != machine_id:
                return error_response('wrong_machine', 'Subscription belongs to another machine'), 403
            sub.p256dh = keys['p256dh']
            sub.auth = keys['auth']
            sub.platform = platform
        
        db.session.add(sub)
        db.session.commit()
        
        status_code = 201 if is_new else 200
        response = jsonify({})
        response.headers['Cache-Control'] = 'no-store'
        return response, status_code
    
    @app.route('/api/v1/push/subscriptions', methods=['DELETE'])
    def unsubscribe_from_push():
        """
        DELETE /push/subscriptions
        Unregister a device from push notifications.
        """
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return error_response('unauthorized', 'Bearer token required'), 401
        
        token = auth_header[7:]
        machine_id = verify_access_token(token)
        if not machine_id:
            return error_response('unauthorized', 'Invalid token'), 401

        limited = enforce_rate_limit(f'push-delete:{token}', limit=300, window_seconds=3600)
        if limited:
            return limited
        
        data = request.get_json()
        if not data or 'endpoint' not in data:
            return jsonify({}), 204
        
        endpoint = data['endpoint']
        sub = Subscription.query.filter_by(endpoint=endpoint).first()
        if sub:
            if sub.machine_id != machine_id:
                return error_response('wrong_machine', 'Subscription belongs to another machine'), 403
            db.session.delete(sub)
            db.session.commit()
        
        response = jsonify({})
        response.headers['Cache-Control'] = 'no-store'
        return response, 204
    
    # ==================== INGEST STATUS (FROM PI) ====================
    @app.route('/api/v1/ingest/status', methods=['POST'])
    def ingest_status():
        """
        POST /ingest/status
        Pi posts reading every 5 minutes.
        HMAC-signed with device secret.
        """
        # Get headers
        device_id = request.headers.get('X-HW-Device-Id')
        timestamp = request.headers.get('X-HW-Timestamp')
        key_id = request.headers.get('X-HW-Key-Id')
        signature = request.headers.get('X-HW-Signature')
        
        if not all([device_id, timestamp, key_id, signature]):
            return error_response('invalid_request', 'Missing required headers'), 422

        try:
            timestamp_int = int(timestamp)
        except (TypeError, ValueError):
            return error_response('unauthorized', 'Invalid timestamp'), 401
        if not re.fullmatch(r'[0-9a-f]{64}', signature):
            return error_response('unauthorized', 'Invalid signature format'), 401
        
        # Get raw body for signature verification
        raw_body = request.get_data()
        
        # Verify signature
        is_valid, msg = verify_hmac_signature(device_id, timestamp_int, raw_body, signature, key_id)
        if not is_valid:
            return error_response('unauthorized', msg), 401

        request_hash = hashlib.sha256(
            b'\n'.join([
                device_id.encode('utf-8'),
                timestamp.encode('utf-8'),
                key_id.encode('utf-8'),
                signature.encode('ascii'),
                raw_body,
            ])
        ).hexdigest()
        db.session.add(IngestRequest(request_hash=request_hash))
        try:
            db.session.flush()
        except IntegrityError:
            db.session.rollback()
            return error_response('duplicate_request', 'Request already accepted'), 409
        
        # Parse body
        try:
            data = request.get_json(silent=False)
        except Exception:
            return error_response('invalid_request', 'Invalid JSON'), 422

        if not isinstance(data, dict):
            return error_response('invalid_request', 'JSON object required'), 422
        
        # Validate body
        if data.get('machineId') != device_id:
            return error_response('invalid_request', 'Device ID mismatch'), 422
        
        liquid = data.get('liquid')
        if not isinstance(liquid, dict):
            return error_response('invalid_request', 'Liquid object required'), 422

        state = liquid.get('state')
        percent = liquid.get('percent')
        
        if state not in ['ok', 'low']:
            return error_response('invalid_request', 'Invalid state value'), 422
        
        if percent is not None and not (
            isinstance(percent, (int, float))
            and not isinstance(percent, bool)
            and math.isfinite(percent)
            and 0 <= percent <= 100
        ):
            return error_response('invalid_request', 'Invalid percent'), 422
        
        ts_str = data.get('ts')
        firmware = data.get('firmware')
        if not isinstance(firmware, str) or not firmware:
            return error_response('invalid_request', 'Firmware required'), 422

        if not isinstance(ts_str, str) or not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z', ts_str
        ):
            return error_response('invalid_request', 'Invalid timestamp'), 422
        try:
            datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            return error_response('invalid_request', 'Invalid timestamp'), 422
        
        # Get or create machine
        machine = Machine.query.get(device_id)
        if not machine:
            return error_response('unauthorized', 'Unknown device'), 401
        
        # Record the reading
        reading = StatusReading(
            machine_id=device_id,
            state=state,
            percent=percent,
            firmware=firmware,
            pi_timestamp=datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        )
        db.session.add(reading)
        
        # Update machine last seen
        machine.last_reading_at = datetime.now(timezone.utc)
        
        # Update confirmed state via state manager
        old_state = machine.state
        state_manager.process_reading(machine, reading)
        
        # Check if we need to send notifications
        if machine.state != old_state or machine.state == 'low':
            logger.info(f"Machine {device_id} state changed from {old_state} to {machine.state}")
            push_manager.send_notifications_for_state_change(
                machine, machine.state, previous_state=old_state
            )
        
        db.session.commit()
        
        response = jsonify({})
        response.headers['Cache-Control'] = 'no-store'
        return response, 202
    
    # ==================== SSE STREAM (OPTIONAL) ====================
    @app.route('/api/v1/machines/<machine_id>/stream', methods=['GET'])
    def stream_machine_status(machine_id):
        """
        GET /machines/{machineId}/stream
        Optional server-sent events. Return 404 to let app fall back to polling.
        """
        return error_response('not_found', 'Streaming not available'), 404
    
    # ==================== HELPERS ====================
    def error_response(code: str, message: str, retry_after: Optional[int] = None):
        """Standard error response format."""
        response = jsonify({
            'error': {
                'code': code,
                'message': message
            }
        })
        response.headers['Cache-Control'] = 'no-store'
        if retry_after is not None:
            response.headers['Retry-After'] = str(retry_after)
        return response

    def enforce_rate_limit(identity: str, limit: int, window_seconds: int):
        """Apply a fixed-window database-backed limit and return a 429 response when exceeded."""
        now = datetime.now(timezone.utc)
        window_start = now.replace(minute=0, second=0, microsecond=0)
        if window_seconds != 3600:
            epoch = int(now.timestamp())
            window_start = datetime.fromtimestamp(
                epoch - (epoch % window_seconds), tz=timezone.utc
            )
        bucket = RateLimitBucket.query.filter_by(
            identity=identity, window_start=window_start
        ).first()
        if bucket is None:
            bucket = RateLimitBucket(identity=identity, window_start=window_start, count=0)
            db.session.add(bucket)
        bucket.count += 1
        if bucket.count > limit:
            db.session.rollback()
            retry_after = max(1, int((window_start + timedelta(seconds=window_seconds) - now).total_seconds()))
            return error_response('rate_limited', 'Too many requests', retry_after), 429
        db.session.commit()
        return None
    
    def verify_access_token(token: str):
        """Verify Bearer token and return machine_id, or None if invalid."""
        from auth import decode_access_token
        return decode_access_token(token)
    
    # ==================== ERROR HANDLERS ====================
    @app.errorhandler(404)
    def not_found(e):
        response = jsonify({
            'error': {
                'code': 'not_found',
                'message': 'Endpoint not found'
            }
        })
        response.headers['Cache-Control'] = 'no-store'
        return response, 404

    @app.errorhandler(400)
    def bad_request(e):
        return error_response('invalid_request', 'Invalid request'), 400

    @app.errorhandler(415)
    def unsupported_media_type(e):
        return error_response('invalid_request', 'Content-Type must be application/json'), 415
    
    @app.errorhandler(405)
    def method_not_allowed(e):
        response = jsonify({
            'error': {
                'code': 'method_not_allowed',
                'message': 'Method not allowed'
            }
        })
        response.headers['Cache-Control'] = 'no-store'
        return response, 405
    
    @app.errorhandler(500)
    def internal_error(e):
        db.session.rollback()
        logger.error(f"Internal error: {e}")
        response = jsonify({
            'error': {
                'code': 'internal_error',
                'message': 'Internal server error'
            }
        })
        response.headers['Cache-Control'] = 'no-store'
        return response, 500
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
