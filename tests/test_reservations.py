import json
from datetime import datetime
from urllib.error import HTTPError
from io import BytesIO
from unittest.mock import patch

import pytest

from patroller_webui.reservations import (ReservationClient, ReservationError,
    local_to_utc, gpu_state, reservation_status, make_payload)


def test_auth_and_payload():
    client = ReservationClient({'url': 'http://127.0.0.1:1', 'reservation_token': 'secret', 'http_auth_user': 'u', 'http_auth_pass': 'p'}, {})
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"id":"1"}'
    with patch('urllib.request.OpenerDirector.open', return_value=Response()) as request:
        client.create({'gpu_uuids': ['gpu-uuid']})
    req = request.call_args.args[0]
    assert req.get_header('Authorization').startswith('Basic ')
    assert req.get_header('X-patroller-reservation-token') == 'secret'
    assert json.loads(req.data)['gpu_uuids'] == ['gpu-uuid']


def test_error_states_and_redaction():
    client = ReservationClient({'url': 'http://127.0.0.1:1'}, {})
    for code, state in [(404, 'unsupported'), (503, 'disabled'), (401, 'read-only'), (409, 'conflict')]:
        with patch('urllib.request.OpenerDirector.open', side_effect=HTTPError('url', code, 'secret', {}, BytesIO(b'{"error":"secret"}'))):
            with pytest.raises(ReservationError) as exc: client.list()
        assert exc.value.state == state
        assert 'secret' not in str(exc.value)


def test_dst_and_payload():
    with pytest.raises(ValueError): local_to_utc(datetime(2026, 3, 29, 2, 30), 'Europe/Ljubljana')
    with pytest.raises(ValueError): local_to_utc(datetime(2026, 10, 25, 2, 30), 'Europe/Ljubljana')
    payload = make_payload(['uuid'], ' a@example.com ', datetime(2026, 1, 1, 12), datetime(2026, 1, 1, 13), 'n', 'Europe/Ljubljana')
    assert payload['start_at'] == '2026-01-01T11:00:00Z'
    assert payload['owner_email'] == 'a@example.com'


def test_dashboard_states():
    assert gpu_state({'claim': {}, 'active_reservation': {'id': 'x'}, 'next_reservation': None}) == ('IDLE', False)
    assert gpu_state({'claim': {}, 'active_reservation': None, 'next_reservation': None}) == ('FREE', True)
    assert gpu_state({'claim': {}}) == ('UNKNOWN', False)
    assert gpu_state({'claim': {'user': 'x'}}) == ('OCCUPIED', False)
    assert reservation_status({'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-02T00:00:00Z'}, datetime.fromisoformat('2026-01-01T00:00:00+00:00')) == 'Active'


def test_write_methods_and_missing_token():
    client = ReservationClient({'url': 'http://127.0.0.1:1', 'reservation_token': 'token'}, {})
    with patch.object(client, '_request', return_value={}) as request:
        client.update('a/b', {'note': 'edit'})
        request.assert_called_with('/reservations/a%2Fb', 'PATCH', {'note': 'edit'})
        client.cancel('a')
        request.assert_called_with('/unreserve', 'POST', {'id': 'a'})
    with pytest.raises(ReservationError) as exc:
        ReservationClient({'url': 'http://127.0.0.1:1'}, {}).create({})
    assert exc.value.state == 'read-only'


def dashboard_fixture():
    from unittest.mock import patch
    from webui_dashboard import run_dashboard
    class FakePatroller:
        cfg = {}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'url': 'http://127.0.0.1', 'data': {
                'uuid': {'claim': {}, 'mem': 0, 'active_reservation': {'id': '1', 'owner_email': 'owner@example.com', 'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-02T00:00:00Z', 'note': 'private note'}, 'next_reservation': None}},
                'devs': {'uuid': {'number': 0, 'name': 'GPU', 'total_mem': '1024 MiB'}}}])
    with patch('webui_dashboard.Patroller', FakePatroller):
        run_dashboard()


def test_dashboard_apptest():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(dashboard_fixture).run()
    assert not app.exception
    assert not any('IDLE' in item.value for item in app.markdown)
    assert any('Total available: 0 / 1' in item.value for item in app.caption)
    assert len(app.get('popover')) == 1
    assert app.get('popover')[0].proto.popover.label == '🔒 RESERVED: owner@example.com'


def reservations_fixture():
    from unittest.mock import patch
    from webui_reservations import run_reservations
    class FakePatroller:
        cfg = {'servers': [{'name': 'node', 'url': 'http://127.0.0.1', 'reservation_token': 'fixture'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'data': {'uuid': {}}, 'devs': {'uuid': {'number': 0, 'name': 'Fixture GPU'}}}])
    class FakeClient:
        writable = True
        def __init__(self, *args): pass
        def list(self):
            return [{'id': 'one', 'gpu_uuids': ['uuid'], 'owner_email': 'a@example.com', 'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-01T01:00:00Z', 'note': ''}]
        def update(self, record_id, payload):
            import streamlit as st
            st.session_state['updated_fixture'] = (record_id, payload)
        def create(self, payload):
            import streamlit as st
            st.session_state['created_fixture'] = payload
        def cancel(self, record_id):
            import streamlit as st
            st.session_state['cancelled_fixture'] = record_id
    with patch('webui_reservations.Patroller', FakePatroller), patch('webui_reservations.ReservationClient', FakeClient):
        run_reservations()


def booking_widget(app, kind, label, create=False):
    """Choose by panel and label, never by the panels' visual order."""
    panel = next(x for x in app.get('expander') if x.label == ('Add reservation' if create else 'Edit reservation'))
    return next(x for x in panel.get(kind) if x.label == label)


def test_management_apptest():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(reservations_fixture).run()
    assert not app.exception
    assert len(app.dataframe) == 1
    # Edit existing record and verify one atomic PATCH payload.
    booking_widget(app, 'text_area', 'Note').set_value('edited')
    next(button for button in app.button if button.label == 'Save changes').click().run()
    assert not app.exception
    record_id, payload = app.session_state['updated_fixture']
    assert record_id == 'one' and payload['note'] == 'edited' and payload['gpu_uuids'] == ['uuid']
    next(button for button in app.button if button.label == 'Cancel reservation').click().run()
    assert next(button for button in app.button if button.label == 'Confirm cancellation').key == 'cancel-confirm:["node", "one"]'
    assert 'cancelled_fixture' not in app.session_state
    next(button for button in app.button if button.label == 'Keep reservation').click().run()
    booking_widget(app, 'multiselect', 'GPUs', create=True).set_value(['uuid'])
    booking_widget(app, 'text_input', 'Owner email', create=True).set_value('new@example.com')
    next(button for button in app.button if button.label == 'Add reservation').click().run()
    assert not app.exception
    assert app.session_state['created_fixture']['gpu_uuids'] == ['uuid']


def test_bearer_and_offline():
    from urllib.error import URLError
    client = ReservationClient({'url': 'http://127.0.0.1:1'}, {'reservation_token': 'fixture'})
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{}'
    with patch('urllib.request.OpenerDirector.open', return_value=Response()) as call:
        client.cancel('id')
    assert call.call_args.args[0].get_header('Authorization') == 'Bearer fixture'
    with patch('urllib.request.OpenerDirector.open', side_effect=URLError('private detail')):
        with pytest.raises(ReservationError) as exc: client.list()
    assert exc.value.state == 'offline' and 'private detail' not in str(exc.value)


def unavailable_fixture():
    from unittest.mock import patch
    from webui_reservations import run_reservations
    from patroller_webui.reservations import ReservationError
    class FakePatroller:
        cfg = {'servers': [{'name': 'old-node', 'url': 'http://127.0.0.1'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
    class FakeClient:
        writable = False
        def __init__(self, *args): pass
        def list(self): raise ReservationError('unsupported', 'Reservation endpoint not found.')
    with patch('webui_reservations.Patroller', FakePatroller), patch('webui_reservations.ReservationClient', FakeClient):
        run_reservations()


def test_unavailable_apptest():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(unavailable_fixture).run()
    assert not app.exception
    assert any('Read-only' in x.value for x in app.info)
    assert any('Unsupported' in x.value for x in app.error)
    assert not any('empty' in x.value.lower() for x in app.info)


def test_redirects_never_reach_other_server():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    received = []
    class Target(BaseHTTPRequestHandler):
        def do_GET(self): received.append(dict(self.headers)); self.send_response(200); self.end_headers(); self.wfile.write(b'[]')
        def do_POST(self): received.append(dict(self.headers)); self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
        def log_message(self, *args): pass
    target = ThreadingHTTPServer(('127.0.0.1', 0), Target)
    class Redirect(BaseHTTPRequestHandler):
        def redirect(self):
            self.send_response(302)
            self.send_header('Location', f'http://127.0.0.1:{target.server_port}/target')
            self.end_headers()
        do_GET = redirect
        do_POST = redirect
        def log_message(self, *args): pass
    source = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    threads = [Thread(target=s.serve_forever, daemon=True) for s in (source, target)]
    for thread in threads: thread.start()
    try:
        url = f'http://127.0.0.1:{source.server_port}'
        for server, operation in [({'url': url, 'http_auth_user': 'u', 'http_auth_pass': 'p'}, 'list'),
                                  ({'url': url, 'reservation_token': 'bearer'}, 'create'),
                                  ({'url': url, 'reservation_token': 'token', 'http_auth_user': 'u', 'http_auth_pass': 'p'}, 'create')]:
            client = ReservationClient(server, {})
            with pytest.raises(ReservationError):
                client.list() if operation == 'list' else client.create({})
        assert received == []
    finally:
        for server in (source, target): server.shutdown(); server.server_close()
        for thread in threads: thread.join()


def test_calendar_day_overlap_boundaries_and_dst():
    from datetime import date
    from patroller_webui.reservations import overlaps_days
    zone = 'Europe/Ljubljana'
    def record(start, end): return {'start_at': start, 'end_at': end}
    day = date(2026, 3, 29)
    assert not overlaps_days(record('2026-03-28T20:00:00Z', '2026-03-28T23:00:00Z'), day, None, zone)
    assert overlaps_days(record('2026-03-28T23:00:00Z', '2026-03-29T01:00:00Z'), day, day, zone)
    assert overlaps_days(record('2026-03-29T21:59:00Z', '2026-03-29T22:01:00Z'), day, day, zone)
    assert not overlaps_days(record('2026-03-29T22:00:00Z', '2026-03-30T00:00:00Z'), None, day, zone)
    fall = date(2026, 10, 25)
    assert overlaps_days(record('2026-10-25T22:30:00Z', '2026-10-25T23:30:00Z'), fall, fall, zone)
    assert not overlaps_days(record('2026-10-25T23:00:00Z', '2026-10-26T00:00:00Z'), None, fall, zone)


def switching_fixture():
    from unittest.mock import patch
    from webui_reservations import run_reservations
    class FakePatroller:
        cfg = {'servers': [{'name': name, 'url': 'http://127.0.0.1', 'reservation_token': 'test'} for name in ('first', 'second')]}
        def __init__(self, *args): pass
        def __len__(self): return 2
        def __iter__(self):
            return iter([{'name': name, 'data': {'uuid': {}}, 'devs': {'uuid': {'number': 0, 'name': 'GPU'}}} for name in ('first', 'second')])
    class FakeClient:
        writable = True
        def __init__(self, server, config): self.server = server
        def list(self):
            return [{'id': id, 'gpu_uuids': ['uuid'], 'owner_email': 'a@example.com', 'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-01T01:00:00Z', 'note': ''} for id in ('one', 'two')]
        def cancel(self, record_id):
            import streamlit as st
            st.session_state['cancelled_switch'] = (self.server['name'], record_id)
    with patch('webui_reservations.Patroller', FakePatroller), patch('webui_reservations.ReservationClient', FakeClient):
        run_reservations()


def test_switching_booking_resets_edit_and_confirmation():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(switching_fixture).run()
    assert not app.exception
    booking_widget(app, 'text_area', 'Note').set_value('unsaved').run()
    next(x for x in app.selectbox if x.label == 'Reservation to manage').select({'id': 'two', 'gpu_uuids': ['uuid'], 'owner_email': 'a@example.com', 'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-01T01:00:00Z', 'note': ''}).run()
    assert booking_widget(app, 'text_area', 'Note').value == ''
    next(b for b in app.button if b.label == 'Cancel reservation').click().run()
    assert next(b for b in app.button if b.label == 'Confirm cancellation').key == 'cancel-confirm:["first", "two"]'
    assert 'cancelled_switch' not in app.session_state
    next(b for b in app.button if b.label == 'Keep reservation').click().run()
    booking_widget(app, 'text_area', 'Note').set_value('other unsaved').run()
    next(x for x in app.selectbox if x.label == 'Server').select('second').run()
    assert not app.exception
    assert booking_widget(app, 'text_area', 'Note').value == ''
    assert not app.checkbox


def test_redirect_handler_rejects_redirect():
    from patroller_webui.reservations import NoRedirect
    import urllib.request
    request = urllib.request.Request('http://127.0.0.1/source', headers={'Authorization': 'Bearer secret'})
    assert NoRedirect().redirect_request(request, None, 302, 'Found', {}, 'http://127.0.0.1/target') is None


def test_duration_payload_and_recurrence_windows():
    from datetime import date, timezone
    from patroller_webui.reservations import make_duration_payload, overlaps_days
    rule = {'frequency': 'weekly', 'until': '2026-04-30', 'timezone': 'Europe/Ljubljana', 'weekdays': [5, 6]}
    p = make_duration_payload(['uuid'], 'a@example.com', datetime(2026, 3, 28, 23, 30), 2.5, '', 'Europe/Ljubljana', rule)
    assert p['start_at'] == '2026-03-28T22:30:00Z'
    assert p['end_at'] == '2026-03-29T01:00:00Z'
    assert p['recurrence'] == rule
    for bad in (True, float('nan'), float('inf'), 0.24, 8784.01):
        with pytest.raises(ValueError):
            make_duration_payload(['uuid'], 'a@example.com', datetime(2026, 1, 1), bad, '', 'Europe/Ljubljana')
    p = make_duration_payload(['uuid'], 'a@example.com', datetime(2026, 1, 1), 49.5, '', 'Europe/Ljubljana')
    assert 'recurrence' not in p
    assert (datetime.fromisoformat(p['end_at'].replace('Z', '+00:00')) - datetime.fromisoformat(p['start_at'].replace('Z', '+00:00'))).total_seconds() == 49.5 * 3600
    record = {'start_at': '2026-01-01T10:00:00Z', 'end_at': '2026-01-01T11:00:00Z', 'occurrences': [
        {'start_at': '2026-01-01T10:00:00Z', 'end_at': '2026-01-01T11:00:00Z'},
        {'start_at': '2026-01-03T10:00:00Z', 'end_at': '2026-01-03T11:00:00Z'}]}
    assert reservation_status(record, datetime(2026, 1, 2, tzinfo=timezone.utc)) == 'Upcoming'
    assert reservation_status(record, datetime(2026, 1, 3, 10, 30, tzinfo=timezone.utc)) == 'Active'
    assert not overlaps_days(record, date(2026, 1, 2), date(2026, 1, 2), 'UTC')


def test_repeat_controls_visible_on_selection():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(reservations_fixture).run()
    repeat = booking_widget(app, 'selectbox', 'Repeat', create=True)
    for choice in ('Daily', 'Weekly', 'Every two weeks', 'Monthly'):
        repeat.select(choice).run()
        assert not app.exception
        assert any(x.label == 'Last repeat date' for x in app.date_input)
        assert not any(x.label == 'Weekdays' for x in app.multiselect)
    assert {x.label for x in app.number_input} >= {'Start hour', 'Start minute', 'Duration (hours)'}
    assert not any(x.label in ('End date', 'End time') for x in list(app.date_input) + list(app.time_input))


def recurring_fixture():
    from unittest.mock import patch
    from webui_reservations import run_reservations
    class FakePatroller:
        cfg = {'timezone': 'UTC', 'servers': [{'name': 'node', 'url': 'http://127.0.0.1', 'reservation_token': 'test'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'data': {'uuid': {}}, 'devs': {'uuid': {'number': 0, 'name': 'GPU'}}}])
    class FakeClient:
        writable = True
        def __init__(self, *args): pass
        def list(self):
            return [{'id': 'series', 'gpu_uuids': ['uuid'], 'owner_email': 'a@example.com',
                     'start_at': '2026-01-05T10:15:00Z', 'end_at': '2026-01-07T11:45:00Z', 'note': 'original',
                     'recurrence': {'frequency': 'weekly', 'until': '2026-02-01', 'timezone': 'UTC', 'weekdays': [0, 2]},
                     'occurrences': [{'start_at': '2026-01-05T10:15:00Z', 'end_at': '2026-01-07T11:45:00Z'},
                                     {'start_at': '2026-01-12T10:15:00Z', 'end_at': '2026-01-14T11:45:00Z'}]}]
        def update(self, id, payload):
            import streamlit as st
            st.session_state['series_update'] = (id, payload)
        def create(self, payload):
            import streamlit as st
            st.session_state['series_create'] = payload
        def cancel(self, id):
            import streamlit as st
            st.session_state['series_cancel'] = id
    with patch('webui_reservations.Patroller', FakePatroller), patch('webui_reservations.ReservationClient', FakeClient):
        run_reservations()


def test_series_edit_create_and_cancel():
    from datetime import date
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(recurring_fixture).run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]['Repeat'] == 'Weekly until 2026-02-01 · 2 bookings'
    assert booking_widget(app, 'selectbox', 'Repeat').value == 'Weekly'
    assert not any(x.label == 'Weekdays' for x in app.multiselect)
    assert booking_widget(app, 'number_input', 'Duration (hours)').value == 49.5
    next(b for b in app.button if b.label == 'Save changes').click().run()
    record_id, payload = app.session_state['series_update']
    assert record_id == 'series' and payload['recurrence']['weekdays'] == [0]
    assert payload['end_at'] == '2026-01-07T11:45:00Z' and 'occurrences' not in payload
    next(b for b in app.button if b.label == 'Cancel reservation').click().run()
    assert next(b for b in app.button if b.label == 'Confirm cancellation').key == 'cancel-confirm:["node", "series"]'
    assert any('entire recurring series' in x.value for x in app.markdown)
    assert 'series_cancel' not in app.session_state
    next(b for b in app.button if b.label == 'Keep reservation').click().run()
    booking_widget(app, 'selectbox', 'Repeat', create=True).select('Daily').run()
    booking_widget(app, 'multiselect', 'GPUs', create=True).set_value(['uuid'])
    booking_widget(app, 'text_input', 'Owner email', create=True).set_value('new@example.com')
    booking_widget(app, 'date_input', 'Start date', create=True).set_value(date(2026, 1, 5))
    booking_widget(app, 'date_input', 'Last repeat date', create=True).set_value(date(2026, 1, 10))
    booking_widget(app, 'number_input', 'Duration (hours)', create=True).set_value(1.5)
    next(b for b in app.button if b.label == 'Add reservation').click().run()
    assert not app.exception
    assert app.session_state['series_create']['recurrence'] == {'frequency': 'daily', 'until': '2026-01-10', 'timezone': 'UTC'}


def test_last_repeat_date_validation():
    from datetime import date
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(reservations_fixture).run()
    booking_widget(app, 'selectbox', 'Repeat', create=True).select('Weekly').run()
    booking_widget(app, 'multiselect', 'GPUs', create=True).set_value(['uuid'])
    booking_widget(app, 'text_input', 'Owner email', create=True).set_value('a@example.com')
    booking_widget(app, 'date_input', 'Start date', create=True).set_value(date(2026, 1, 5))
    booking_widget(app, 'date_input', 'Last repeat date', create=True).set_value(date(2027, 1, 7))
    next(b for b in app.button if b.label == 'Add reservation').click().run()
    assert any('366 days' in x.value for x in app.error)
    booking_widget(app, 'date_input', 'Last repeat date', create=True).set_value(date(2026, 1, 10))
    booking_widget(app, 'date_input', 'Last repeat date', create=True).set_value(date(2026, 1, 4))
    next(b for b in app.button if b.label == 'Add reservation').click().run()
    assert any('on or after Start date' in x.value for x in app.error)


@pytest.mark.parametrize('choice,frequency', [('Daily', 'daily'), ('Weekly', 'weekly'), ('Every two weeks', 'biweekly'), ('Monthly', 'monthly')])
def test_create_each_recurrence(choice, frequency):
    from datetime import date
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(reservations_fixture).run()
    booking_widget(app, 'selectbox', 'Repeat', create=True).select(choice).run()
    booking_widget(app, 'multiselect', 'GPUs', create=True).set_value(['uuid'])
    booking_widget(app, 'text_input', 'Owner email', create=True).set_value('a@example.com')
    booking_widget(app, 'date_input', 'Start date', create=True).set_value(date(2026, 1, 5))
    booking_widget(app, 'date_input', 'Last repeat date', create=True).set_value(date(2026, 2, 5))
    next(b for b in app.button if b.label == 'Add reservation').click().run()
    rule = app.session_state['created_fixture']['recurrence']
    assert rule['frequency'] == frequency
    assert rule.get('weekdays') == ([0] if choice in ('Weekly', 'Every two weeks') else None)


def test_duration_fall_transition_and_status_after_series():
    from datetime import timezone
    from patroller_webui.reservations import make_duration_payload
    payload = make_duration_payload(['uuid'], 'a@example.com', datetime(2026, 10, 25, 1, 30), 2, '', 'Europe/Ljubljana')
    assert payload['start_at'] == '2026-10-24T23:30:00Z'
    assert payload['end_at'] == '2026-10-25T01:30:00Z'
    record = {'start_at': payload['start_at'], 'end_at': payload['end_at'], 'occurrences': [payload]}
    assert reservation_status(record, datetime(2026, 10, 25, 1, 30, tzinfo=timezone.utc)) == 'Past'


def legacy_duration_fixture():
    import streamlit as st
    from webui_reservations import booking_form
    class Client:
        writable = True
        def update(self, record_id, payload):
            st.session_state['legacy_payload'] = payload
        def create(self, payload):
            st.session_state['legacy_created'] = payload
    record = {'id': 'legacy', 'gpu_uuids': ['uuid'], 'owner_email': 'a@example.com',
              'start_at': '2026-01-01T00:00:00.123456Z', 'end_at': st.session_state['legacy_end'], 'note': ''}
    booking_form(Client(), {'uuid': {'number': 0, 'name': 'GPU'}}, {}, 'UTC', 'node', record)
    booking_form(Client(), {'uuid': {'number': 0, 'name': 'GPU'}}, {}, 'UTC', 'node')


@pytest.mark.parametrize('end', ['2026-01-01T00:05:00.123457Z', '2027-01-03T00:00:00.123457Z'])
def test_legacy_duration_render_and_edit(end):
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(legacy_duration_fixture)
    app.session_state['legacy_end'] = end
    app.run()
    assert not app.exception
    app.text_area[0].set_value('changed')
    next(b for b in app.button if b.label == 'Save changes').click().run()
    assert not app.exception
    assert app.session_state['legacy_payload']['end_at'] == end
    assert any(b.label == 'Add reservation' for b in app.button)


def advancing_clock_fixture():
    import streamlit as st
    from datetime import datetime as real_datetime
    from unittest.mock import patch
    import webui_reservations as ui
    class Clock(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 1, 1, 10, st.session_state.get('clock_minute', 0), tzinfo=tz)
    class Client:
        writable = True
        def create(self, payload):
            st.session_state['clock_payload'] = payload
    with patch.object(ui, 'datetime', Clock):
        ui.booking_form(Client(), {'uuid': {'number': 0, 'name': 'GPU'}}, {}, 'UTC', 'node')


def test_creation_draft_survives_clock_advance():
    from datetime import date
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(advancing_clock_fixture).run()
    app.number_input[1].set_value(45)
    next(x for x in app.selectbox if x.label == 'Repeat').select('Daily').run()
    app.session_state['clock_minute'] = 1
    next(x for x in app.selectbox if x.label == 'Repeat').select('Weekly').run()
    assert app.number_input[1].value == 45
    app.multiselect[0].set_value(['uuid'])
    app.text_input[0].set_value('a@example.com')
    next(x for x in app.date_input if x.label == 'Last repeat date').set_value(date(2026, 1, 2))
    next(b for b in app.button if b.label == 'Add reservation').click().run()
    assert app.session_state['clock_payload']['start_at'] == '2026-01-01T10:45:00Z'


def test_legacy_duration_exception_only_for_unchanged_value():
    from datetime import timedelta
    from patroller_webui.reservations import make_duration_payload
    original = timedelta(minutes=5, microseconds=1)
    args = (['uuid'], 'a@example.com', datetime(2026, 1, 1), original.total_seconds() / 3600, '', 'UTC')
    payload = make_duration_payload(*args, original_duration=original)
    assert payload['end_at'] == '2026-01-01T00:05:00.000001Z'
    with pytest.raises(ValueError):
        make_duration_payload(*args[:3], 0.1, *args[4:], original_duration=original)
    with pytest.raises(ValueError):
        make_duration_payload(*args)
