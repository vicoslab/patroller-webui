"""Time remaining until the next reservation starts, not its end time."""
from datetime import datetime, timedelta, timezone

import pytest

from patroller_webui import reservations


NOW = datetime(2030, 1, 2, 6, 45, tzinfo=timezone.utc)


@pytest.mark.parametrize('seconds, expected', [
    (-1, '<1m'), (0, '<1m'), (1, '<1m'), (59, '<1m'),
    (60, '1m'), (3599, '59m'), (3600, '1h'), (8100, '2h 15m'),
    (86400, '1d'), (94500, '1d 2h 15m'),
])
def test_time_to_start_formats_compact_units(seconds, expected):
    record = {'start_at': (NOW + timedelta(seconds=seconds)).isoformat(),
              'end_at': (NOW + timedelta(days=4)).isoformat()}
    assert reservations.reservation_countdown(record, now=NOW) == expected


def test_time_to_start_handles_non_utc_offsets():
    assert reservations.reservation_countdown({'start_at': '2030-01-02T10:00:00+01:00'}, now=NOW) == '2h 15m'


def test_time_to_start_uses_current_clock_when_not_supplied(monkeypatch):
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)
    monkeypatch.setattr(reservations, 'datetime', FixedDateTime)
    assert reservations.reservation_countdown({'start_at': '2030-01-02T09:00:00Z'}) == '2h 15m'
