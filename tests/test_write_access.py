"""Browser credentials never inherit the service's legacy write token."""
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

from patroller_webui.reservations import ReservationClient, ReservationError


@pytest.mark.parametrize('basic', [False, True])
def test_verify_uses_authenticated_nonmutating_get(basic):
    server = {'url': 'http://127.0.0.1:1', 'reservation_token': 'browser-secret'}
    if basic:
        server.update(http_auth_user='u', http_auth_pass='p')
    client = ReservationClient(server, {})
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"writable":true}'
    with patch('urllib.request.OpenerDirector.open', return_value=Response()) as request:
        assert client.verify_write_access() is True
    req = request.call_args.args[0]
    assert req.full_url == 'http://127.0.0.1:1/reservation-access'
    assert req.get_method() == 'GET' and req.data is None
    if basic:
        assert req.get_header('Authorization').startswith('Basic ')
        assert req.get_header('X-patroller-reservation-token') == 'browser-secret'
    else:
        assert req.get_header('Authorization') == 'Bearer browser-secret'


@pytest.mark.parametrize('status', [200, 201, 202, 203, 204, 206, 299])
def test_verification_requires_http_200(status):
    import io
    from urllib.response import addinfourl
    from email.message import Message
    client = ReservationClient({'url': 'http://127.0.0.1:1', 'reservation_token': 'fixture-only'}, {})
    response = addinfourl(io.BytesIO(b'{"writable":true}'), Message(),
                          'http://127.0.0.1:1/reservation-access', code=status)
    with patch('urllib.request.OpenerDirector.open', return_value=response):
        if status == 200:
            assert client.verify_write_access() is True
        else:
            with pytest.raises(ReservationError):
                client.verify_write_access()


def test_crud_still_accepts_http_201():
    import io
    from urllib.response import addinfourl
    from email.message import Message
    client = ReservationClient({'url': 'http://127.0.0.1:1', 'reservation_token': 'fixture-only'}, {})
    response = addinfourl(io.BytesIO(b'{"id":"fixture-booking"}'), Message(),
                          'http://127.0.0.1:1/reserve', code=201)
    with patch('urllib.request.OpenerDirector.open', return_value=response):
        assert client.create({'fixture': True}) == {'id': 'fixture-booking'}


@pytest.mark.parametrize('result', [None, [], {}, {'writable': False}, {'writable': 1}, {'writable': 'true'}])
def test_verify_requires_strict_true(result):
    client = ReservationClient({'url': 'http://127.0.0.1:1', 'reservation_token': 'candidate'}, {})
    with patch.object(client, '_request', return_value=result) as request:
        assert client.verify_write_access() is False
    request.assert_called_once_with('/reservation-access', authenticated=True)


def test_verify_missing_token_never_opens_request():
    client = ReservationClient({'url': 'http://127.0.0.1:1', 'reservation_token': ''}, {'reservation_token': 'legacy'})
    with patch('urllib.request.OpenerDirector.open') as request:
        assert client.verify_write_access() is False
    request.assert_not_called()


def access_fixture():
    import streamlit as st
    from unittest.mock import patch
    from patroller_webui.write_access import capture_url_token, configure_write_access
    from patroller_webui.reservations import ReservationError
    capture_url_token()
    selected = st.selectbox('Node', ['first', 'second'])
    server = {'name': selected, 'url': 'http://127.0.0.1:1', 'reservation_token': 'legacy-node'}
    config = {'reservation_token': 'legacy-global', 'servers': [server]}
    before = repr(config)
    def request(client, path, method='GET', payload=None, authenticated=False):
        st.session_state['checks'] = st.session_state.get('checks', []) + [(selected, client.token, path, method, authenticated)]
        if st.session_state.get('unsupported'):
            raise ReservationError('unsupported', 'private browser-secret detail')
        return {'writable': client.token == 'browser-secret' and selected == 'first'}
    with patch('patroller_webui.reservations.ReservationClient._request', request):
        client = configure_write_access(server, config)
    st.session_state['client_token'] = client.token
    st.session_state['config_unchanged'] = repr(config) == before
    st.button('Write booking', disabled=not client.writable)
    st.text_input('Booking draft', key='booking_draft')


def button(app, label):
    return next(x for x in app.button if x.label == label)


def token_input(app):
    return next(x for x in app.text_input if x.label == 'Write token')


def unlock(app, token):
    token_input(app).set_value(token)
    return button(app, 'Unlock reservations').click().run()


def test_missing_token_ignores_legacy_config_and_masks_input():
    app = AppTest.from_function(access_fixture).run()
    assert not app.exception
    assert button(app, 'Write booking').disabled
    assert token_input(app).proto.type == token_input(app).proto.PASSWORD
    assert app.session_state['client_token'] == ''
    assert app.session_state['config_unchanged']
    assert 'checks' not in app.session_state


def test_explicit_unlock_clear_and_node_reverify_preserve_draft():
    app = AppTest.from_function(access_fixture).run()
    assert not app.exception
    next(x for x in app.text_input if x.label == 'Booking draft').set_value('unsaved booking').run()
    unlock(app, 'browser-secret')
    assert not app.exception
    assert not button(app, 'Write booking').disabled
    assert not any(x.label == 'Write token' for x in app.text_input)
    assert not any(x.label in ('Unlock reservations', 'Clear write token') for x in app.button)
    assert not app.success
    assert 'browser-secret' not in ' '.join(x.value for kind in (app.markdown, app.info, app.success, app.error) for x in kind)
    app.selectbox[0].select('second').run()
    assert button(app, 'Write booking').disabled
    assert app.session_state['checks'][-1] == ('second', 'browser-secret', '/reservation-access', 'GET', True)
    app.selectbox[0].select('first').run()
    assert not button(app, 'Write booking').disabled
    app.query_params['write-token'] = ''
    app.run()
    assert not app.exception
    assert button(app, 'Write booking').disabled
    assert token_input(app).value == ''
    assert next(x for x in app.text_input if x.label == 'Booking draft').value == 'unsaved booking'
    assert app.session_state['config_unchanged']


def test_invalid_and_unsupported_candidates_remain_readonly_and_redacted():
    app = AppTest.from_function(access_fixture).run()
    assert not app.exception
    unlock(app, 'invalid-secret')
    assert button(app, 'Write booking').disabled and app.error
    assert app.session_state['client_token'] == ''
    unlock(app, 'browser-secret')
    app.session_state['unsupported'] = True
    app.run()
    assert button(app, 'Write booking').disabled
    assert 'browser-secret' not in ' '.join(x.value for x in app.error)
    assert app.session_state['checks'][-1][1] == 'browser-secret'


def test_url_token_wins_is_removed_and_does_not_cross_sessions():
    app = AppTest.from_function(access_fixture)
    app.query_params['write-token'] = 'browser-secret'
    app.query_params['other'] = ['one', 'two']
    app.run()
    assert not app.exception
    assert not button(app, 'Write booking').disabled
    assert 'write-token' not in app.query_params
    assert app.query_params['other'] == ['one', 'two']
    other = AppTest.from_function(access_fixture).run()
    assert not other.exception
    assert button(other, 'Write booking').disabled
    app.query_params['write-token'] = 'replacement'
    app.run()
    assert button(app, 'Write booking').disabled
    assert app.session_state['checks'][-1][1] == 'replacement'
    assert token_input(app).value == ''


@pytest.mark.parametrize('values', [[''], ['browser-secret', 'browser-secret'], ['bad token'], ['bad\ncontrol'], ['é'], ['x' * 4097]])
def test_malformed_url_clears_previous_token_and_preserves_other_query(values):
    app = AppTest.from_function(access_fixture)
    app.query_params['write-token'] = 'browser-secret'
    app.run()
    assert not app.exception
    assert not button(app, 'Write booking').disabled
    app.query_params['write-token'] = values
    app.query_params['keep'] = 'value'
    app.run()
    assert not app.exception
    assert button(app, 'Write booking').disabled
    assert app.session_state['client_token'] == ''
    assert 'write-token' not in app.query_params
    assert app.query_params['keep'] == ['value']
    assert app.error
    assert not any(value and value in x.value for value in values for x in app.error)


@pytest.mark.parametrize('value', ['bad token', 'bad\ncontrol', 'é', 'x' * 4097, ''])
def test_malformed_textbox_fails_closed_without_verification(value):
    app = AppTest.from_function(access_fixture).run()
    assert not app.exception
    checks = len((app.session_state['checks'] if 'checks' in app.session_state else []))
    unlock(app, value)
    assert not app.exception
    assert button(app, 'Write booking').disabled
    assert len((app.session_state['checks'] if 'checks' in app.session_state else [])) == checks
    assert token_input(app).value == ''


def test_entrypoint_captures_before_navigation():
    import ast
    from pathlib import Path
    source = Path(__file__).parents[1] / 'patroller_webui' / 'webui.py'
    run = next(node for node in ast.parse(source.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == 'run')
    calls = [node for node in ast.walk(run) if isinstance(node, ast.Call)]
    capture = next((node.lineno for node in calls if isinstance(node.func, ast.Name) and node.func.id == 'capture_url_token'), None)
    navigation = next(node.lineno for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == 'navigation')
    assert capture is not None and capture < navigation


def standalone_page_fixture():
    import streamlit as st
    from unittest.mock import patch
    from webui_reservations import run_reservations
    class Patroller:
        cfg = {'reservation_token': 'legacy-global', 'servers': [{'name': 'node', 'url': 'http://127.0.0.1:1', 'reservation_token': 'legacy-node'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self): return iter([{'name': 'node', 'data': {'uuid': {}}, 'devs': {'uuid': {'number': 0, 'name': 'GPU'}}}])
    def request(client, path, method='GET', payload=None, authenticated=False):
        st.session_state['page_requests'] = st.session_state.get('page_requests', []) + [(path, client.token)]
        if path == '/reservation-access': return {'writable': client.token == 'browser-secret'}
        return []
    with patch('webui_reservations.Patroller', Patroller), patch('patroller_webui.reservations.ReservationClient._request', request):
        run_reservations()


def test_standalone_page_only_unlocks_after_browser_token_verification():
    app = AppTest.from_function(standalone_page_fixture).run()
    assert not app.exception
    assert not any(x.label == 'Add reservation' for x in app.button)
    assert app.session_state['page_requests'] == [('/reservations', '')]
    app.query_params['write-token'] = 'browser-secret'
    app.run()
    assert not app.exception
    assert not button(app, 'Add reservation').disabled
    assert 'write-token' not in app.query_params
    app.text_area[0].set_value('keep this unsaved booking').run()
    app.query_params['write-token'] = ''
    app.run()
    assert not any(x.label == 'Add reservation' for x in app.button)
    assert not app.text_area
    assert [x.label for x in app.expander] == ['Reservations list']
    app.query_params['write-token'] = 'browser-secret'
    app.run()
    assert not button(app, 'Add reservation').disabled
