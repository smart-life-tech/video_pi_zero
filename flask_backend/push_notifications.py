"""Push notification handling."""

from models import db, Machine, Subscription, NotificationLog
from config import Config
from datetime import datetime, timezone, timedelta
import logging
import json

logger = logging.getLogger(__name__)

try:
    from pywebpush import webpush, WebPushException
    HAS_WEBPUSH = True
except ImportError:
    HAS_WEBPUSH = False
    logger.warning('pywebpush not installed - push notifications disabled')


class PushNotificationManager:
    """Handles Web Push notifications."""
    
    def __init__(self):
        self.vapid_public = Config.VAPID_PUBLIC_KEY
        self.vapid_private = Config.VAPID_PRIVATE_KEY
        self.vapid_email = Config.VAPID_ADMIN_EMAIL
    
    def send_notifications_for_state_change(self, machine: Machine, new_state: str):
        """
        Send notifications to subscribed devices when machine state changes.
        
        Logic from contract section 8:
        - Notify only on level drops (transitions to warn/low)
        - Don't notify on rises
        - At most one reminder every 12 hours while machine stays low
        """
        # Get subscriptions for this machine
        subscriptions = Subscription.query.filter_by(machine_id=machine.id).all()
        
        if not subscriptions:
            logger.info(f'No subscriptions for {machine.id}')
            return
        
        # Determine if we should notify
        should_notify = self._should_notify(machine, new_state)
        
        if not should_notify:
            logger.info(f'Skipping notification for {machine.id} -> {new_state}')
            return
        
        # Prepare notification payload
        payload = self._build_payload(machine, new_state)
        
        # Send to each subscription
        for subscription in subscriptions:
            self._send_to_subscription(machine, subscription, payload, new_state)
        
        # Update notification timestamp
        machine.last_notification_at = datetime.now(timezone.utc)
        db.session.commit()
    
    def _should_notify(self, machine: Machine, new_state: str) -> bool:
        """
        Determine if we should send a notification.
        
        Rules:
        - Only notify on drop (warn or low from ok)
        - Only notify on rise if it's been 12+ hours since last notification
        - Never notify on ok (no notification on recovery)
        """
        old_state = machine.state
        
        # Map state transitions
        is_drop = (
            (old_state == 'ok' and new_state in ['warn', 'low']) or
            (old_state == 'warn' and new_state == 'low')
        )
        
        if not is_drop:
            # Check if it's been 12 hours for a reminder
            if new_state == 'low' and machine.last_notification_at:
                elapsed = datetime.now(timezone.utc) - machine.last_notification_at
                min_interval = timedelta(hours=12)
                if elapsed < min_interval:
                    return False
            else:
                return False
        
        return True
    
    def _build_payload(self, machine: Machine, state: str) -> dict:
        """Build the push notification payload."""
        
        state_text = {
            'ok': 'Tank full',
            'warn': 'Tank running low',
            'low': 'Tank critically low'
        }.get(state, state)
        
        percent = machine.last_confirmed_percent
        percent_text = f' ({percent}%)' if percent is not None else ''
        
        return {
            'title': f'{machine.name}',
            'body': f'{state_text}{percent_text}',
            'tag': f'machine-{machine.id}',
            'data': {
                'machineId': machine.id,
                'state': state,
                'percent': percent
            }
        }
    
    def _send_to_subscription(self, machine: Machine, subscription: Subscription, payload: dict, state: str):
        """Send notification to a single subscription endpoint."""
        
        if not HAS_WEBPUSH:
            logger.warning('pywebpush not available, skipping send')
            return
        
        log_entry = NotificationLog(
            machine_id=machine.id,
            subscription_id=subscription.id,
            state_change=f'state-change-{state}'
        )
        
        try:
            webpush(
                subscription_info={
                    'endpoint': subscription.endpoint,
                    'keys': {
                        'p256dh': subscription.p256dh,
                        'auth': subscription.auth
                    }
                },
                data=json.dumps(payload),
                vapid_private_key=self.vapid_private,
                vapid_claims={
                    'sub': f'mailto:{self.vapid_email}'
                }
            )
            
            log_entry.status = 'sent'
            subscription.last_push_at = datetime.now(timezone.utc)
            subscription.failed_pushes = 0
            
            logger.info(f'Notification sent to {machine.id} ({subscription.platform})')
            
        except WebPushException as e:
            log_entry.status = 'failed'
            subscription.failed_pushes = subscription.failed_pushes + 1
            
            # If endpoint is gone, delete subscription
            if e.status == 410:  # Gone
                logger.info(f'Endpoint {machine.id} is gone, deleting subscription')
                db.session.delete(subscription)
            
            logger.warning(f'Push failed for {machine.id}: {e}')
        
        except Exception as e:
            log_entry.status = 'failed'
            logger.error(f'Error sending push to {machine.id}: {e}')
        
        db.session.add(log_entry)
        db.session.commit()
    
    def cleanup_expired_subscriptions(self):
        """Remove subscriptions that have failed too many times."""
        failed = Subscription.query.filter(
            Subscription.failed_pushes > 5
        ).all()
        
        for sub in failed:
            logger.info(f'Removing repeatedly-failed subscription for {sub.machine_id}')
            db.session.delete(sub)
        
        db.session.commit()
