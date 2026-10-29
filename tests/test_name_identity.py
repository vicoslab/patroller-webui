"""Frozen name identity contract, with synthetic UI and history data only."""
from datetime import datetime, timedelta

import pytest
from streamlit.testing.v1 import AppTest
from test_owner_input import widget
from test_dashboard_reservation_display import render

NAME = 'toolbox-nanoparticles'


def test_name_duration_payload_and_legacy_shape():
    from patroller_webui.reservations import make_duration_payload
    original = timedelta(minutes=5, microseconds=1)
    payload = make_duration_payload(['gpu'], '', datetime(2030, 1, 1), original.total_seconds() / 3600,
                                    '', 'UTC', original_duration=original, owner_name=f' {NAME} ', owner_type='name')
    assert payload['owner_type'] == 'name' and payload['owner_email'] == '' and payload['owner_name'] == NAME
    assert payload['end_at'] == '2030-01-01T00:05:00.000001Z'
    email = make_duration_payload(['gpu'], ' A@Example.org ', datetime(2030, 1, 1), 1, '', 'UTC', owner_name=NAME)
    assert email['owner_email'] == 'a@example.org' and 'owner_type' not in email


@pytest.mark.parametrize('name', ['', 'Unknown', ' unknown USER ', 'N/A', 'none', 'NULL', 42, None, 'x'*201, 'a\nb', 'x\x7f'])
def test_invalid_name_payload(name):
    from patroller_webui.reservations import make_duration_payload
    with pytest.raises(ValueError):
        make_duration_payload(['gpu'], '', datetime(2030, 1, 1), 1, '', 'UTC', owner_name=name, owner_type='name')


@pytest.mark.parametrize('kind,email', [('name', 'a@example.org'), ('email', 'a@example.org'), ('other', '')])
def test_mixed_or_unknown_identity_payload(kind, email):
    from patroller_webui.reservations import make_duration_payload
    with pytest.raises(ValueError):
        make_duration_payload(['gpu'], email, datetime(2030, 1, 1), 1, '', 'UTC', owner_name=NAME, owner_type=kind)


@pytest.mark.parametrize('user_label', [None, 'ccc-user.name', 'name'])
def test_original_occupied_container_label(user_label):
    app = render({'ccc-user.name': NAME, 'email': 'N/A'}, user_label=user_label)
    assert [p.proto.popover.label for p in app.get('popover')] == [f'❌ OCCUPIED: {NAME}']


def test_name_reservation_dashboard_details_and_empty_config_email():
    from test_dashboard_reservation_display import BOOKING
    record = dict(BOOKING, owner_email='', owner_type='name', owner_name=NAME)
    app = render(active=record, upcoming=record, users=[{'email': '', 'name': 'Wrong person'}])
    assert app.get('popover')[0].proto.popover.label == f'🔒 RESERVED: Container: {NAME}'
    assert any(f'Container: {NAME}' in x.value for x in app.markdown)
    # Malformed empty legacy email must not accidentally match an empty config entry.
    app = render(active=dict(BOOKING, owner_email=''), users=[{'email': '', 'name': 'Wrong person'}])
    assert 'Wrong person' not in app.get('popover')[0].proto.popover.label


def name_form_fixture(edit=False):
    NAME = 'toolbox-nanoparticles'
    import streamlit as st
    from webui_reservations import booking_form
    class Client:
        writable = True
        def create(self, payload): st.session_state['saved_name'] = payload
        def update(self, record_id, payload): st.session_state['saved_name'] = payload
    record = {'id': 'name-record', 'owner_email': '', 'owner_type': 'name', 'owner_name': NAME,
              'gpu_uuids': ['gpu'], 'start_at': '2030-01-01T09:15:00.123456Z',
              'end_at': '2030-01-01T09:20:00.123457Z'} if edit else None
    options = [{'email': 'a@example.org', 'name': NAME}]
    if not st.session_state.get('remove_name'):
        options.append({'email': '', 'owner_type': 'name', 'name': NAME})
    booking_form(Client(), {'gpu': {'number': 0, 'name': 'GPU'}}, {}, 'UTC', 'node', record, options)


def test_custom_name_submit_and_identity_drafts_off_on():
    app = AppTest.from_function(name_form_fixture).run()
    assert widget(app, 'selectbox', 'Owner identity').value == 'Email'
    widget(app, 'text_input', 'Owner email').set_value('draft@example.org').run()
    widget(app, 'text_input', 'Owner name (optional)').set_value('Email display').run()
    widget(app, 'selectbox', 'Owner identity').select('Container name').run()
    field = widget(app, 'text_input', 'Container name')
    assert 'ccc-user.name' in field.proto.help and 'case-sensitive' in field.proto.help
    field.set_value(NAME).run()
    widget(app, 'selectbox', 'Owner identity').select('Email').run()
    assert widget(app, 'text_input', 'Owner email').value == 'draft@example.org'
    assert widget(app, 'text_input', 'Owner name (optional)').value == 'Email display'
    widget(app, 'selectbox', 'Owner identity').select('Container name').run()
    assert widget(app, 'text_input', 'Container name').value == NAME
    widget(app, 'selectbox', 'Owner').select('a@example.org').run()
    widget(app, 'selectbox', 'Repeat').select('Daily').run()
    widget(app, 'selectbox', 'Owner').select('__custom__').run()
    assert widget(app, 'selectbox', 'Owner identity').value == 'Container name'
    assert widget(app, 'text_input', 'Container name').value == NAME
    assert 'saved_name' not in app.session_state
    widget(app, 'multiselect', 'GPUs').set_value(['gpu'])
    widget(app, 'button', 'Add reservation').click().run()
    assert not app.exception
    saved = app.session_state['saved_name']
    assert saved['owner_type'] == 'name' and saved['owner_email'] == '' and saved['owner_name'] == NAME
    assert saved['recurrence']['frequency'] == 'daily'


@pytest.mark.parametrize('custom', [False, True])
def test_name_edit_and_known_refresh(custom):
    app = AppTest.from_function(name_form_fixture, args=(True,)).run()
    assert widget(app, 'selectbox', 'Owner').value == f'name:{NAME}'
    app.session_state['remove_name'] = True
    app.run()
    assert widget(app, 'selectbox', 'Owner').value == f'name:{NAME}'
    if custom:
        widget(app, 'selectbox', 'Owner').select('__custom__').run()
        assert widget(app, 'selectbox', 'Owner identity').value == 'Container name'
        assert widget(app, 'text_input', 'Container name').value == NAME
    widget(app, 'button', 'Save changes').click().run()
    assert not app.exception
    saved = app.session_state['saved_name']
    assert saved['owner_email'] == '' and saved['owner_type'] == 'name' and saved['owner_name'] == NAME
    assert saved['end_at'] == '2030-01-01T09:20:00.123457Z'


def name_list_fixture():
    import streamlit as st
    st.session_state.setdefault('reservation_browser_token', 'synthetic-browser')
    from unittest.mock import patch
    from webui_reservations import run_reservations
    class Patroller:
        cfg = {'servers': [{'name': 'node', 'url': 'http://fixture', 'reservation_token': 'fixture'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'data': {'gpu': {'claim': {'user': {'ccc-user.name': 'live-container', 'email': 'N/A'}}}},
                          'devs': {'gpu': {'number': 0, 'name': 'GPU'}}}])
    class Client:
        writable = True
        def verify_write_access(self): return True
        def __init__(self, *args): pass
        def list(self):
            return [{'id': name, 'owner_type': 'name', 'owner_email': '', 'owner_name': name,
                     'gpu_uuids': ['gpu'], 'start_at': '2030-01-01T09:00:00Z', 'end_at': '2030-01-01T10:00:00Z'}
                    for name in ('toolbox-nanoparticles', 'another-container')]
        def cancel(self, record_id): st.session_state['name_cancelled'] = record_id
    with patch('webui_reservations.Patroller', Patroller), patch('patroller_webui.write_access.ReservationClient', Client):
        run_reservations()


def test_name_filter_table_manage_cancel_and_live_suggestions():
    app = AppTest.from_function(name_list_fixture).run()
    assert not app.exception
    assert 'Container: live-container' in widget(app, 'selectbox', 'Owner').options
    selector = widget(app, 'selectbox', 'Reservation to manage')
    assert all('Container:' in label for label in selector.options)
    widget(app, 'multiselect', 'Filter owners').set_value([f'name:{NAME}']).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 1
    assert app.dataframe[0].value.iloc[0]['Owner'] == f'Container: {NAME}'
    widget(app, 'button', 'Cancel reservation').click().run()
    assert any(f'Container: {NAME}' in x.value for x in app.markdown)
    assert 'name_cancelled' not in app.session_state
    assert widget(app, 'button', 'Confirm cancellation').key == f'cancel-confirm:["node", "{NAME}"]'


def name_dialog_fixture():
    import streamlit as st
    from webui_reservations import confirm_cancellation
    class Client:
        writable = True
        def cancel(self, record_id): st.session_state['name_cancelled'] = record_id
    if 'name_cancelled' not in st.session_state:
        confirm_cancellation(Client(), 'node', {'id': 'captured-name', 'owner_type': 'name', 'owner_email': '',
                                              'owner_name': 'toolbox-nanoparticles', 'start_at': '2030-01-01T09:00:00Z'}, 'UTC')


def test_name_cancellation_captures_identity_and_record():
    # AppTest1.36 requires a separately mounted modal for fragment actions.
    app = AppTest.from_function(name_dialog_fixture).run()
    assert not app.exception
    assert any(f'Container: {NAME}' in x.value for x in app.markdown)
    widget(app, 'button', 'Confirm cancellation').click().run()
    assert not app.exception
    assert app.session_state['name_cancelled'] == 'captured-name'


def test_local_identity_namespaces_and_email_precedence():
    from patroller_webui.identity import process_identity, reservation_identity, owner_key
    assert process_identity({'email': ' A@EXAMPLE.ORG ', 'ccc-user.name': NAME}) == ('email', 'a@example.org')
    assert process_identity({'email': 'N/A', 'ccc-user.name': 'Unknown', 'name': ' Generic '}) == ('name', 'Generic')
    assert process_identity({'email': 'N/A', 'ccc-user.name': 'Case'}) == ('name', 'Case')
    assert process_identity({'email': 'N/A', 'ccc-user.name': 'case'}) == ('name', 'case')
    assert reservation_identity({'owner_email': '', 'owner_name': NAME}) is None
    assert reservation_identity({'owner_email': 'a@example.org', 'owner_name': NAME}) == ('email', 'a@example.org')
    assert reservation_identity({'owner_email': 'a@example.org', 'owner_type': 'name', 'owner_name': NAME}) is None
    assert reservation_identity({'owner_email': '', 'owner_type': 'email', 'owner_name': NAME}) is None
    assert owner_key({'owner_email': '', 'owner_type': 'name', 'owner_name': 'a@example.org'}) == 'name:a@example.org'
    assert owner_key({'owner_email': 'a@example.org', 'owner_name': NAME}) == 'a@example.org'


def test_known_name_create_refresh_and_custom_draft_survive():
    app = AppTest.from_function(name_form_fixture).run()
    assert not app.exception
    widget(app, 'selectbox', 'Owner identity').select('Container name').run()
    widget(app, 'text_input', 'Container name').set_value('custom-draft').run()
    widget(app, 'selectbox', 'Owner').select(f'name:{NAME}').run()
    assert not app.text_input
    app.session_state['remove_name'] = True
    app.run()
    assert widget(app, 'selectbox', 'Owner').value == f'name:{NAME}'
    assert 'saved_name' not in app.session_state
    widget(app, 'selectbox', 'Owner').select('__custom__').run()
    assert widget(app, 'selectbox', 'Owner identity').value == 'Container name'
    assert widget(app, 'text_input', 'Container name').value == 'custom-draft'
    app.session_state['remove_name'] = False
    app.run()
    widget(app, 'selectbox', 'Owner').select(f'name:{NAME}').run()
    widget(app, 'multiselect', 'GPUs').set_value(['gpu'])
    widget(app, 'button', 'Add reservation').click().run()
    assert not app.exception
    assert app.session_state['saved_name']['owner_type'] == 'name'
    assert app.session_state['saved_name']['owner_name'] == NAME
    assert app.session_state['saved_name']['owner_email'] == ''


@pytest.mark.parametrize('value,expected', [
    (' .a@example.org ', None), ('a.@example.org', None), ('a..b@example.org', None),
    ('a@-example.org', None), ('a@example-.org', None), ('a@example.123', None),
    ('é@example.org', None), ('a' * 65 + '@example.org', None),
    ('name:a@example.org', None), ('a@' + 'x' * 64 + '.org', None),
    (' A+TAG@EXAMPLE.ORG ', 'a+tag@example.org'), ('a' * 64 + '@example.org', 'a' * 64 + '@example.org'),
    (' ' * 513 + 'A@example.org', 'a@example.org'), (None, None),
])
def test_email_backend_rule_parity_and_name_fallback(value, expected):
    from patroller_webui.identity import identity_email, process_identity, owner_key
    assert identity_email(value) == expected
    if expected is None:
        assert process_identity({'email': value, 'ccc-user.name': NAME}) == ('name', NAME)
    assert owner_key({'owner_email': 'name:a@example.org'}) != owner_key(
        {'owner_type': 'name', 'owner_email': '', 'owner_name': 'a@example.org'})


def shared_claims_fixture():
    import streamlit as st
    from unittest.mock import patch
    from webui_reservations import run_reservations
    class Patroller:
        cfg = {'servers': [{'name': 'node', 'url': 'http://fixture'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'devs': {}, 'data': {
                'shared': {'claim': {'user': {'email': 'first@example.org'}, 'users': [
                    {'email': 'first@example.org'}, {'ccc-user.name': 'second-container'}, 'bad', None]}},
                'legacy': {'claim': {'user': {'ccc-user.name': 'legacy-container'}}},
                'malformed': {'claim': 'bad'}, 'bad_users': {'claim': {'users': 'bad', 'user': {'ccc-user.name': 'fallback-container'}}},
                'bad_info': 'bad'}}])
    class Client:
        writable = False
        def __init__(self, *args): pass
        def list(self): return []
    def capture(records, config, history_path, users):
        st.session_state['claim_users'] = users
        return []
    with patch('webui_reservations.Patroller', Patroller), patch('patroller_webui.write_access.ReservationClient', Client), patch('webui_reservations.suggestions', capture):
        run_reservations()


def test_shared_claims_collect_all_users_and_legacy_fallback():
    app = AppTest.from_function(shared_claims_fixture).run()
    assert not app.exception
    assert app.session_state['claim_users'] == [
        {'email': 'first@example.org'}, {'ccc-user.name': 'second-container'},
        {'ccc-user.name': 'legacy-container'}, {'ccc-user.name': 'fallback-container'}]
