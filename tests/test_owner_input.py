"""Known owners stay compact; custom owners can always enter email/name."""
import pytest
from streamlit.testing.v1 import AppTest


def owner_fixture(configured=True, edit=False):
    import streamlit as st
    from webui_reservations import booking_form
    class Client:
        writable = True
        def create(self, payload): st.session_state['owner_created'] = payload
        def update(self, record_id, payload): st.session_state['owner_updated'] = (record_id, payload)
    config = {'reservation_users': [{'email': 'known@example.org', 'name': 'Known Person'}]} if configured else {}
    record = {'id': 'existing', 'gpu_uuids': ['uuid'], 'owner_email': 'old@example.org', 'owner_name': 'Old Person',
              'start_at': '2030-01-07T09:15:00Z', 'end_at': '2030-01-07T10:45:00Z'} if edit else None
    options = [{'email': 'known@example.org', 'name': 'Known Person'}, {'email': 'mailonly@example.org', 'name': ''}]
    if st.session_state.get('more_owners'):
        options.append({'email': 'aaa.new@example.org', 'name': 'New History Entry'})
    if st.session_state.get('remove_known'):
        options = [item for item in options if item['email'] != 'known@example.org']
    booking_form(Client(), {'uuid': {'number': 0, 'name': 'GPU'}}, config, 'UTC', 'node', record, owner_options=options)


def widget(app, kind, label):
    return next(x for x in getattr(app, kind) if x.label == label)


@pytest.mark.parametrize('configured', [True, False])
def test_custom_owner_accepts_arbitrary_email_and_optional_name(configured):
    app = AppTest.from_function(owner_fixture, args=(configured, False)).run()
    assert not app.exception
    owner = widget(app, 'selectbox', 'Owner')
    assert owner.value == '__custom__' and 'New / custom owner' in owner.options
    email = widget(app, 'text_input', 'Owner email')
    assert email.value == '' and 'CCC' in email.proto.help
    email.set_value('new.person@example.org').run()
    widget(app, 'text_input', 'Owner name (optional)').set_value('New Person').run()
    widget(app, 'multiselect', 'GPUs').set_value(['uuid'])
    widget(app, 'button', 'Add reservation').click().run()
    assert not app.exception
    assert app.session_state['owner_created']['owner_email'] == 'new.person@example.org'
    assert app.session_state['owner_created']['owner_name'] == 'New Person'


def test_known_owner_hides_custom_fields_and_requires_explicit_submit():
    app = AppTest.from_function(owner_fixture).run()
    widget(app, 'selectbox', 'Owner').select('known@example.org').run()
    assert not app.exception
    assert not app.text_input
    assert not app.get('popover'), 'No separate suggestions popover should be necessary'
    assert 'owner_created' not in app.session_state
    widget(app, 'multiselect', 'GPUs').set_value(['uuid'])
    widget(app, 'button', 'Add reservation').click().run()
    assert app.session_state['owner_created']['owner_email'] == 'known@example.org'
    assert app.session_state['owner_created']['owner_name'] == 'Known Person'


@pytest.mark.parametrize('change', ['more_owners', 'remove_known'])
def test_history_option_refresh_keeps_selected_owner_without_writing(change):
    app = AppTest.from_function(owner_fixture).run()
    widget(app, 'selectbox', 'Owner').select('known@example.org').run()
    app.session_state[change] = True
    app.run()
    assert not app.exception
    assert widget(app, 'selectbox', 'Owner').value == 'known@example.org'
    assert not app.text_input
    assert 'owner_created' not in app.session_state


def test_custom_draft_survives_known_owner_toggle_and_repeat_rerun():
    app = AppTest.from_function(owner_fixture).run()
    widget(app, 'text_input', 'Owner email').set_value('someone.new@example.org').run()
    widget(app, 'text_input', 'Owner name (optional)').set_value('Someone New').run()
    widget(app, 'selectbox', 'Owner').select('known@example.org').run()
    widget(app, 'selectbox', 'Repeat').select('Daily').run()
    widget(app, 'selectbox', 'Owner').select('__custom__').run()
    assert not app.exception
    assert widget(app, 'text_input', 'Owner email').value == 'someone.new@example.org'
    assert widget(app, 'text_input', 'Owner name (optional)').value == 'Someone New'
    assert 'owner_created' not in app.session_state
    widget(app, 'text_input', 'Owner email').set_value('another@example.org').run()
    assert widget(app, 'text_input', 'Owner name (optional)').value == ''


def test_owner_edit_defaults_known_but_custom_prefills_and_can_remove_name():
    app = AppTest.from_function(owner_fixture, args=(True, True)).run()
    assert widget(app, 'selectbox', 'Owner').value == 'old@example.org'
    assert not app.text_input
    widget(app, 'selectbox', 'Owner').select('__custom__').run()
    assert widget(app, 'text_input', 'Owner email').value == 'old@example.org'
    assert widget(app, 'text_input', 'Owner name (optional)').value == 'Old Person'
    widget(app, 'text_input', 'Owner name (optional)').set_value('').run()
    widget(app, 'button', 'Save changes').click().run()
    assert not app.exception
    record_id, saved = app.session_state['owner_updated']
    assert record_id == 'existing' and saved['owner_email'] == 'old@example.org'
    assert 'owner_name' not in saved


@pytest.mark.parametrize('name', [42, None, '\x00Name', 'Name\nOther', 'x' * 201])
def test_optional_name_validation(name):
    from datetime import datetime
    from patroller_webui.reservations import make_duration_payload
    if name is None:
        assert 'owner_name' not in make_duration_payload(['uuid'], 'new@example.org', datetime(2030, 1, 7), 1, '', 'UTC', owner_name=name)
    else:
        with pytest.raises(ValueError):
            make_duration_payload(['uuid'], 'new@example.org', datetime(2030, 1, 7), 1, '', 'UTC', owner_name=name)


def test_name_does_not_replace_required_email():
    from datetime import datetime
    from patroller_webui.reservations import make_duration_payload
    with pytest.raises(ValueError):
        make_duration_payload(['uuid'], '', datetime(2030, 1, 7), 1, '', 'UTC', owner_name='A Person')
