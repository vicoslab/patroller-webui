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


def test_management_apptest():
    from streamlit.testing.v1 import AppTest
    app = AppTest.from_function(reservations_fixture).run()
    assert not app.exception
    assert len(app.dataframe) == 1
    # Edit existing record and verify one atomic PATCH payload.
    app.text_area[0].set_value('edited')
    next(button for button in app.button if button.label == 'Save changes').click().run()
    assert not app.exception
    record_id, payload = app.session_state['updated_fixture']
    assert record_id == 'one' and payload['note'] == 'edited' and payload['gpu_uuids'] == ['uuid']
    app.checkbox[0].check()
    next(button for button in app.button if button.label == 'Cancel reservation').click().run()
    assert app.session_state['cancelled_fixture'] == 'one'
    app.multiselect[-1].set_value(['uuid'])
    app.text_input[-1].set_value('new@example.com')
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
    app.text_area[0].set_value('unsaved').run()
    app.checkbox[0].check().run()
    app.selectbox[1].select({'id': 'two', 'gpu_uuids': ['uuid'], 'owner_email': 'a@example.com', 'start_at': '2026-01-01T00:00:00Z', 'end_at': '2026-01-01T01:00:00Z', 'note': ''}).run()
    assert app.text_area[0].value == ''
    assert not app.checkbox[0].value
    next(b for b in app.button if b.label == 'Cancel reservation').click().run()
    assert any('Confirm cancellation' in error.value for error in app.error)
    app.text_area[0].set_value('other unsaved').run()
    app.checkbox[0].check().run()
    app.selectbox[0].select('second').run()
    assert not app.exception
    assert app.text_area[0].value == ''
    assert not app.checkbox[0].value


def test_redirect_handler_rejects_redirect():
    from patroller_webui.reservations import NoRedirect
    import urllib.request
    request = urllib.request.Request('http://127.0.0.1/source', headers={'Authorization': 'Bearer secret'})
    assert NoRedirect().redirect_request(request, None, 302, 'Found', {}, 'http://127.0.0.1/target') is None
