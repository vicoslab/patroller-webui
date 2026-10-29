"""Reservation API and timezone helpers. Credentials remain server-side."""
import base64
import json
import math
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from patroller_webui.identity import identity_name, identity_email


class ReservationError(Exception):
    def __init__(self, state, message):
        super().__init__(message)
        self.state = state


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ReservationClient:
    def __init__(self, server, config):
        self.server = server
        self.config = config
        self.token = server.get('reservation_token', config.get('reservation_token'))

    @property
    def writable(self):
        return bool(self.token)

    def _request(self, path, method='GET', payload=None):
        headers = {'Accept': 'application/json'}
        user = self.server.get('http_auth_user', self.config.get('http_auth_user'))
        password = self.server.get('http_auth_pass', self.config.get('http_auth_pass'))
        basic = bool(user and password and not self.server.get('disable_auth'))
        if basic:
            encoded = base64.b64encode(f'{user}:{password}'.encode()).decode()
            headers['Authorization'] = f'Basic {encoded}'
        if method != 'GET':
            if not self.token:
                raise ReservationError('read-only', 'No reservation write credential is configured.')
            headers['X-Patroller-Reservation-Token' if basic else 'Authorization'] = self.token if basic else f'Bearer {self.token}'
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.server['url'].rstrip('/') + path,
                                     data=json.dumps(payload).encode() if payload is not None else None,
                                     headers=headers, method=method)
        try:
            with urllib.request.build_opener(NoRedirect()).open(req, timeout=5) as response:
                return json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            states = {401: ('read-only', 'Authorization failed.'), 403: ('read-only', 'Write access denied.'),
                      404: ('unsupported' if method == 'GET' else 'not-found', 'Reservation endpoint or record not found.'),
                      409: ('conflict', 'The reservation conflicts with another booking.'),
                      503: ('disabled', 'Reservations are disabled or unavailable on this server.'),
                      400: ('invalid', 'The server rejected the reservation data.'),
                      **{code: ('error', 'Reservation redirects are not allowed.') for code in (301, 302, 303, 307, 308)}}
            state, message = states.get(exc.code, ('error', 'Reservation request failed.'))
            raise ReservationError(state, message) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise ReservationError('offline', 'Server unavailable or returned an invalid response.') from None

    def list(self):
        result = self._request('/reservations')
        if not isinstance(result, list):
            raise ReservationError('error', 'Server returned an invalid reservation list.')
        return result

    def create(self, payload):
        return self._request('/reserve', 'POST', payload)

    def update(self, record_id, payload):
        return self._request('/reservations/' + urllib.parse.quote(record_id, safe=''), 'PATCH', payload)

    def cancel(self, record_id):
        return self._request('/unreserve', 'POST', {'id': record_id})


def local_to_utc(value, zone):
    tz = ZoneInfo(zone)
    candidates = []
    for fold in (0, 1):
        aware = value.replace(tzinfo=tz, fold=fold)
        utc = aware.astimezone(timezone.utc)
        if utc.astimezone(tz).replace(tzinfo=None) == value and utc not in candidates:
            candidates.append(utc)
    if len(candidates) != 1:
        raise ValueError('Local time is ambiguous or does not exist due to daylight saving time.')
    return candidates[0]


def make_payload(gpus, owner, start, end, note, zone, recurrence=None, owner_name=None, owner_type=None):
    identity = _payload_identity(owner, owner_name, owner_type)
    if not gpus or len(set(gpus)) != len(gpus):
        raise ValueError('Select at least one GPU.')
    start_utc, end_utc = local_to_utc(start, zone), local_to_utc(end, zone)
    if end_utc <= start_utc:
        raise ValueError('End must be after start.')
    payload = {'gpu_uuids': gpus, **identity, 'start_at': start_utc.isoformat().replace('+00:00', 'Z'),
               'end_at': end_utc.isoformat().replace('+00:00', 'Z'), 'note': note}
    if recurrence is not None:
        payload['recurrence'] = recurrence
    return payload


def make_duration_payload(gpus, owner, start, duration, note, zone, recurrence=None, original_duration=None, owner_name=None, owner_type=None):
    unchanged = (isinstance(original_duration, timedelta) and original_duration > timedelta(0)
                 and duration == original_duration.total_seconds() / 3600)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or not (0.25 <= duration <= 8784 or unchanged):
        raise ValueError('Duration must be between 0.25 and 8784 hours.')
    start_utc = local_to_utc(start, zone)
    identity = _payload_identity(owner, owner_name, owner_type)
    if not gpus or len(set(gpus)) != len(gpus):
        raise ValueError('Select at least one GPU.')
    end_utc = start_utc + (original_duration if unchanged else timedelta(hours=duration))
    payload = {'gpu_uuids': gpus, **identity, 'start_at': start_utc.isoformat().replace('+00:00', 'Z'),
               'end_at': end_utc.isoformat().replace('+00:00', 'Z'), 'note': note}
    if recurrence is not None:
        payload['recurrence'] = recurrence
    return payload


def _payload_identity(owner, owner_name, owner_type):
    if owner_type is not None:
        name = identity_name(owner_name)
        if owner_type != 'name' or owner != '' or name is None:
            raise ValueError('Container name identity requires an empty email and a valid container name.')
        return {'owner_type': 'name', 'owner_email': '', 'owner_name': name}
    email = identity_email(owner)
    if not email:
        raise ValueError('Enter a valid owner email.')
    result = {'owner_email': email}
    if owner_name is not None:
        if (not isinstance(owner_name, str) or len(owner_name) > 200
                or any(ord(char) < 32 or ord(char) == 127 for char in owner_name)):
            raise ValueError('Owner name must be plain text, at most 200 characters.')
        if owner_name.strip():
            result['owner_name'] = owner_name.strip()
    return result


def parse_time(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def overlaps_days(record, after, before, zone):
    tz = ZoneInfo(zone)
    return any(_window_overlaps_days(window, after, before, tz) for window in record.get('occurrences', [record]))


def _window_overlaps_days(record, after, before, tz):
    start, end = parse_time(record['start_at']), parse_time(record['end_at'])
    if after and end <= datetime.combine(after, time.min, tzinfo=tz).astimezone(timezone.utc):
        return False
    if before and start >= datetime.combine(before + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc):
        return False
    return True


def reservation_countdown(record, now=None):
    """Compact time to the start of restrictions, recomputed on dashboard refresh."""
    now = now or datetime.now(timezone.utc)
    seconds = max(0, int((parse_time(record['start_at']) - now).total_seconds()))
    if seconds < 60:
        return '<1m'
    days, remaining = divmod(seconds // 60, 24 * 60)
    hours, minutes = divmod(remaining, 60)
    return ' '.join(f'{value}{unit}' for value, unit in
                    ((days, 'd'), (hours, 'h'), (minutes, 'm')) if value)


def reservation_status(record, now=None):
    now = now or datetime.now(timezone.utc)
    windows = record.get('occurrences', [record])
    if any(parse_time(w['start_at']) <= now < parse_time(w['end_at']) for w in windows): return 'Active'
    if any(now < parse_time(w['start_at']) for w in windows): return 'Upcoming'
    return 'Past'


def gpu_state(info):
    if (info.get('claim') or {}).get('user') is not None:
        return 'OCCUPIED', False
    if (info.get('reservation_state') == 'unavailable' or
            'active_reservation' not in info or 'next_reservation' not in info):
        return 'UNKNOWN', False
    if info['active_reservation']:
        return 'IDLE', False
    return 'FREE', True
