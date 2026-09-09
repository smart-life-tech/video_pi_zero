"""Database initialization and management."""

from app import create_app, db
from models import Machine, DeviceSecret, PairingCode
from auth import add_device_secret
import secrets
import string


def init_db():
    """Initialize the database (create tables)."""
    app = create_app()
    with app.app_context():
        db.create_all()
        print('Database initialized.')


def seed_machine(machine_id: str, name: str, device_secret: str):
    """
    Add a machine to the database.
    Used during provisioning.
    
    Args:
        machine_id: hw-000123
        name: Display name like "Genesis — Moto Zagos"
        device_secret: Shared secret for HMAC (must match Pi's firmware)
    """
    app = create_app()
    with app.app_context():
        # Create machine
        machine = Machine.query.get(machine_id)
        if machine:
            print(f'Machine {machine_id} already exists, updating...')
            machine.name = name
        else:
            machine = Machine(id=machine_id, name=name)
            db.session.add(machine)
        
        # Add secret
        secret = add_device_secret(machine_id, 'v1', device_secret)
        db.session.add(secret)
        
        db.session.commit()
        print(f'Machine {machine_id} added/updated.')


def generate_pairing_code(machine_id: str, count: int = 1) -> list:
    """
    Generate one-time pairing codes for a machine.
    These are printed on the machine sticker.
    
    Args:
        machine_id: hw-000123
        count: How many codes to generate
    
    Returns: List of pairing codes
    """
    app = create_app()
    with app.app_context():
        machine = Machine.query.get(machine_id)
        if not machine:
            print(f'Machine {machine_id} not found')
            return []
        
        codes = []
        for _ in range(count):
            # Generate code like "GEN-4821"
            code = ''.join(secrets.choice(string.ascii_uppercase) for _ in range(3))
            code += '-' + ''.join(secrets.choice(string.digits) for _ in range(4))
            
            pairing = PairingCode(code=code, machine_id=machine_id)
            db.session.add(pairing)
            codes.append(code)
        
        db.session.commit()
        print(f'Generated {count} pairing codes for {machine_id}:')
        for code in codes:
            print(f'  {code}')
        
        return codes


def reset_db():
    """Drop all tables and reinitialize."""
    app = create_app()
    with app.app_context():
        db.drop_all()
        db.create_all()
        print('Database reset.')


def show_machines():
    """List all machines in the database."""
    app = create_app()
    with app.app_context():
        machines = Machine.query.all()
        if not machines:
            print('No machines found.')
            return
        
        for m in machines:
            print(f'{m.id}: {m.name}')
            print(f'  State: {m.state}')
            print(f'  Last seen: {m.last_reading_at}')
            print(f'  Percent: {m.last_confirmed_percent}%')
            print()


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print('Usage:')
        print('  python database.py init                           # Create tables')
        print('  python database.py reset                          # Drop and recreate')
        print('  python database.py seed <id> <name> <secret>      # Add machine')
        print('  python database.py codes <id> [count]             # Generate pairing codes')
        print('  python database.py machines                       # List machines')
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == 'init':
        init_db()
    elif cmd == 'reset':
        if input('Are you sure? This will delete all data. (y/N): ').lower() == 'y':
            reset_db()
    elif cmd == 'seed':
        if len(sys.argv) < 5:
            print('Usage: python database.py seed <id> <name> <secret>')
            sys.exit(1)
        machine_id = sys.argv[2]
        name = sys.argv[3]
        secret = sys.argv[4]
        seed_machine(machine_id, name, secret)
    elif cmd == 'codes':
        if len(sys.argv) < 3:
            print('Usage: python database.py codes <id> [count]')
            sys.exit(1)
        machine_id = sys.argv[2]
        count = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        generate_pairing_code(machine_id, count)
    elif cmd == 'machines':
        show_machines()
    else:
        print(f'Unknown command: {cmd}')
        sys.exit(1)
