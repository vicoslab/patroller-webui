"""Dashboard reservation state takes precedence only during the active window."""
import pytest
from streamlit.testing.v1 import AppTest


BOOKING = {'id': 'active', 'owner_email': 'alice@example.org',
           'start_at': '2030-01-01T09:00:00Z', 'end_at': '2030-01-01T10:00:00Z',
           'note': 'Active booking details'}
UPCOMING = dict(BOOKING, id='next', owner_email='bob@example.org',
                start_at='2030-01-02T09:00:00Z', end_at='2030-01-02T10:00:00Z',
                note='Future booking details')


def dashboard_display_fixture(claim_user, active, upcoming, users, user_label):
    from unittest.mock import patch
    from datetime import datetime, timezone
    from webui_dashboard import run_dashboard

    class FakePatroller:
        cfg = {'reservation_users': users, 'timezone': 'Europe/Ljubljana', 'user_label': user_label}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'url': 'http://127.0.0.1',
                          'data': {'gpu': {'claim': {'user': claim_user, 'age': 10}, 'mem': 0,
                                           'active_reservation': active, 'next_reservation': upcoming}},
                          'devs': {'gpu': {'number': 0, 'name': 'GPU', 'total_mem': '24576 MiB'}}}])

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2030, 1, 2, 6, 45, tzinfo=timezone.utc).astimezone(tz)

    with patch('webui_dashboard.Patroller', FakePatroller), patch('patroller_webui.reservations.datetime', FixedDateTime):
        run_dashboard()


def render(claim_user=None, active=None, upcoming=None, users=None, user_label=None):
    app = AppTest.from_function(dashboard_display_fixture,
                               args=(claim_user, active, upcoming, users or [], user_label)).run()
    assert not app.exception
    return app


@pytest.mark.parametrize('claim_user', [None, {'email': 'alice@example.org', 'name': 'Alice'},
                                       {'email': 'other@example.org', 'name': 'Other user'}])
def test_active_reservation_replaces_idle_or_occupied_status(claim_user):
    app = render(claim_user, BOOKING, users=[{'email': 'ALICE@example.org', 'name': 'Alice'}])
    labels = [item.proto.popover.label for item in app.get('popover')]
    assert labels == ['🔒 RESERVED: Alice']
    assert not any('IDLE' in item.value or 'FREE' in item.value for item in app.markdown)
    assert any('Total available: 0 / 1' in item.value for item in app.caption)
    assert any(BOOKING['note'] in item.value for item in app.markdown)


def test_active_reservation_owner_falls_back_to_email():
    app = render(active=BOOKING)
    assert [item.proto.popover.label for item in app.get('popover')] == ['🔒 RESERVED: alice@example.org']


def test_explicit_owner_name_takes_precedence_but_email_stays_visible_in_details():
    record = dict(BOOKING, owner_name='New Person')
    app = render(active=record, users=[{'email': 'alice@example.org', 'name': 'Old mapping'}])
    assert [x.proto.popover.label for x in app.get('popover')] == ['🔒 RESERVED: New Person']
    assert any('alice@example.org' in x.value for x in app.markdown)


@pytest.mark.parametrize('claim_user', [None, {'email': 'other@example.org', 'name': 'Other user'}])
def test_future_reservation_has_separate_unlocked_details_button(claim_user):
    app = render(claim_user, upcoming=UPCOMING)
    labels = [item.proto.popover.label for item in app.get('popover')]
    if claim_user:
        assert labels == ['❌ OCCUPIED: Other user', '🔓 Reservations in 2h 15m']
    else:
        assert labels == ['🔓 Reservations in 2h 15m']
        assert any('✔️ FREE' in item.value for item in app.markdown)
        assert any('Total available: 1 / 1' in item.value for item in app.caption)
    assert not any('RESERVED:' in label or '🔒' in label for label in labels)


def test_active_with_upcoming_keeps_one_primary_reserved_button_and_both_details():
    app = render(active=BOOKING, upcoming=UPCOMING)
    assert [item.proto.popover.label for item in app.get('popover')] == ['🔒 RESERVED: alice@example.org']
    for record in (BOOKING, UPCOMING):
        assert any(record['note'] in item.value for item in app.markdown)


def test_active_reservation_name_is_not_overridden_by_occupancy_user_label():
    app = render(active=BOOKING, users=[{'email': 'alice@example.org', 'name': 'Alice'}],
                 user_label='email')
    assert [item.proto.popover.label for item in app.get('popover')] == ['🔒 RESERVED: Alice']


def test_unreserved_status_unchanged():
    free = render()
    assert not free.get('popover')
    assert any('✔️ FREE' in item.value for item in free.markdown)
    occupied = render({'email': 'other@example.org', 'name': 'Other user'})
    assert [item.proto.popover.label for item in occupied.get('popover')] == ['❌ OCCUPIED: Other user']


@pytest.mark.parametrize('kind', ['active', 'upcoming'])
@pytest.mark.parametrize('start,end,duration,start_label', [
    ('2030-01-01T09:00:00Z', '2030-01-01T10:00:00Z', '1 hour', '2030-01-01 10:00'),
    ('2030-01-01T09:00:00Z', '2030-01-01T10:30:00Z', '1.5 hours', '2030-01-01 10:00'),
    ('2030-01-01T09:00:00Z', '2030-01-03T10:30:00Z', '49.5 hours', '2030-01-01 10:00'),
    ('2026-03-29T00:30:00Z', '2026-03-29T02:30:00Z', '2 hours', '2026-03-29 01:30'),
])
def test_reservation_details_show_start_and_elapsed_duration(kind, start, end, duration, start_label):
    record = dict(BOOKING, start_at=start, end_at=end)
    app = render(**{'active' if kind == 'active' else 'upcoming': record})
    details = '\n'.join(item.value for item in app.get('popover')[0].get('markdown'))
    assert f'Start: {start_label} (Europe/Ljubljana)' in details
    assert f'Duration: {duration}' in details
    assert ' – ' not in details and 'End:' not in details
