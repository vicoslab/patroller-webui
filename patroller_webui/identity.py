"""Local advisory identity helpers; no backend imports or authorization decisions."""
import re

_EMAIL = re.compile(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
                    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
                    r"[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
_PLACEHOLDERS = {'unknown', 'unknown user', 'n/a', 'none', 'null'}


def identity_name(value):
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return None
    value = value.strip()
    return value if 1 <= len(value) <= 200 and value.casefold() not in _PLACEHOLDERS else None


def identity_email(value):
    if not isinstance(value, str):
        return None
    value = value.strip().casefold()
    if len(value) > 254 or not _EMAIL.fullmatch(value):
        return None
    local = value.split('@', 1)[0]
    return value if len(local) <= 64 and not local.startswith('.') and not local.endswith('.') and '..' not in local else None


def process_identity(user):
    if not isinstance(user, dict):
        return None
    email = identity_email(user.get('email'))
    if email:
        return 'email', email
    name = identity_name(user.get('ccc-user.name')) or identity_name(user.get('name'))
    return ('name', name) if name else None


def reservation_identity(record):
    if not isinstance(record, dict):
        return None
    if 'owner_type' in record:
        name = identity_name(record.get('owner_name'))
        return ('name', name) if record['owner_type'] == 'name' and record.get('owner_email') == '' and name else None
    email = identity_email(record.get('owner_email'))
    return ('email', email) if email else None


def owner_key(record):
    identity = reservation_identity(record)
    if identity:
        kind, value = identity
        return f'name:{value}' if kind == 'name' else value
    return ''


def owner_label(record):
    identity = reservation_identity(record)
    if identity and identity[0] == 'name':
        return f'Container: {identity[1]}'
    return record.get('owner_email', '')
