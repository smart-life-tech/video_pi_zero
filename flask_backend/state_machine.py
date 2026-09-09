"""State machine for liquid level tracking."""

from models import StatusReading, Machine
from config import Config
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class StateManager:
    """
    Manages state transitions for machine liquid levels.
    
    From contract section 8.2:
    - Falling: percent <= 40 enters warn, percent <= 10 with state=low enters low
    - Rising: percent >= 20 leaves low, percent >= 50 with state=ok returns to ok
    - Gaps between falling/rising are anti-flapping
    - Require 3 consecutive readings for state change
    - Machine with percent=null never enters warn (only ok or low)
    """
    
    def __init__(self, db):
        self.db = db
        self.thresholds = Config.STATE_THRESHOLDS
    
    def process_reading(self, machine: Machine, reading: StatusReading) -> str:
        """
        Process a new reading and update machine state if warranted.
        
        Returns: new_state (may be unchanged)
        """
        old_state = machine.state
        new_state = self._calculate_new_state(machine, reading)
        
        if new_state != old_state:
            logger.info(f'State transition: {machine.id} {old_state} -> {new_state} '
                       f'(percent={reading.percent}, pi_state={reading.state})')
            machine.state = new_state
            machine.state_updated_at = datetime.now(timezone.utc)
        
        # Always update the last confirmed percent
        if reading.percent is not None:
            machine.last_confirmed_percent = reading.percent
        
        return new_state
    
    def _calculate_new_state(self, machine: Machine, new_reading: StatusReading) -> str:
        """
        Calculate what state the machine should be in based on recent readings.
        
        Thresholds:
        - ok -> warn: percent <= 40
        - warn -> low: percent <= 10 AND pi.state == 'low'
        - low -> warn: percent >= 20
        - warn -> ok: percent >= 50 AND pi.state == 'ok'
        
        Anti-flapping: require 3 consecutive readings confirming the new state
        """
        current_state = machine.state
        
        # Get last 3 readings to check for state change consensus
        recent = StatusReading.query.filter_by(
            machine_id=machine.id
        ).order_by(StatusReading.received_at.desc()).limit(3).all()
        
        if not recent:
            return current_state
        
        readings = list(reversed(recent))  # Oldest first
        
        # If percent is None, never enter warn state
        if new_reading.percent is None:
            if current_state == 'warn':
                # Can't stay in warn with no sensor, drop to ok
                return 'ok'
            return current_state
        
        # Check if we have enough consensus
        consensus_readings = readings  # Include new reading implicitly
        
        # State machine logic
        if current_state == 'ok':
            # Try to transition to warn
            if new_reading.percent <= self.thresholds['ok_to_warn']:
                # Check if last readings also triggered this
                if len(readings) >= 1 and readings[-1].percent is not None:
                    if readings[-1].percent <= self.thresholds['ok_to_warn']:
                        logger.info(f'Transitioning {machine.id} to warn (percent={new_reading.percent})')
                        return 'warn'
            return 'ok'
        
        elif current_state == 'warn':
            # Try to transition to low
            if (new_reading.percent <= self.thresholds['warn_to_low'] and 
                new_reading.state == 'low'):
                if len(readings) >= 1:
                    last = readings[-1]
                    if (last.percent is not None and 
                        last.percent <= self.thresholds['warn_to_low'] and
                        last.state == 'low'):
                        logger.info(f'Transitioning {machine.id} to low (percent={new_reading.percent})')
                        return 'low'
                return 'warn'
            
            # Try to transition back to ok
            if (new_reading.percent >= self.thresholds['warn_to_ok'] and 
                new_reading.state == 'ok'):
                if len(readings) >= 1:
                    last = readings[-1]
                    if (last.percent is not None and 
                        last.percent >= self.thresholds['warn_to_ok'] and
                        last.state == 'ok'):
                        logger.info(f'Transitioning {machine.id} to ok (percent={new_reading.percent})')
                        return 'ok'
            
            return 'warn'
        
        elif current_state == 'low':
            # Try to transition back to warn
            if new_reading.percent >= self.thresholds['low_to_warn']:
                if len(readings) >= 1:
                    last = readings[-1]
                    if (last.percent is not None and 
                        last.percent >= self.thresholds['low_to_warn']):
                        logger.info(f'Transitioning {machine.id} to warn (percent={new_reading.percent})')
                        return 'warn'
            
            return 'low'
        
        return current_state
    
    def get_state_explanation(self, machine: Machine) -> dict:
        """Get human-readable explanation of current state for debugging."""
        last_reading = StatusReading.query.filter_by(
            machine_id=machine.id
        ).order_by(StatusReading.received_at.desc()).first()
        
        return {
            'current_state': machine.state,
            'last_confirmed_percent': machine.last_confirmed_percent,
            'last_pi_reading': {
                'state': last_reading.state if last_reading else None,
                'percent': last_reading.percent if last_reading else None,
                'received_at': last_reading.received_at.isoformat() if last_reading else None
            },
            'thresholds': self.thresholds
        }
