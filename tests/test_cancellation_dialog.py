"""Modal actions tested separately from Streamlit1.36 AppTest's full-app reruns."""
import inspect
from contextlib import nullcontext
from unittest.mock import Mock

import pytest
from streamlit.testing.v1 import AppTest


def dialog_fixture(series):
    import streamlit as st
    from webui_reservations import confirm_cancellation

    class Client:
        writable = True

        def cancel(self, record_id):
            st.session_state['modal_cancelled'] = record_id

    record = {'id': 'series' if series else 'one', 'owner_email': 'alice@example.org',
              'start_at': '2030-01-07T09:15:00Z'}
    if series:
        record['recurrence'] = {'frequency': 'weekly'}
    # AppTest1.36 does not execute fragment-only reruns. Keep the same modal
    # mounted until its confirmation requests a full rerun and the record is gone.
    if 'modal_cancelled' not in st.session_state:
        confirm_cancellation(Client(), 'node', record, 'UTC')


@pytest.mark.parametrize('series', [False, True])
def test_dialog_confirm_cancels_only_the_captured_record(series):
    app = AppTest.from_function(dialog_fixture, args=(series,)).run()
    assert not app.exception
    assert 'modal_cancelled' not in app.session_state
    next(button for button in app.button if button.label == 'Confirm cancellation').click().run()
    assert not app.exception
    assert app.session_state['modal_cancelled'] == ('series' if series else 'one')
    # AppTest1.36 retains stale dialog nodes; real-browser acceptance checks closure.


@pytest.mark.parametrize('action', ['keep', 'confirm', 'error'])
def test_dialog_action_guards_and_error_handling(monkeypatch, action):
    import webui_reservations as ui
    from patroller_webui.reservations import ReservationError

    class Rerun(Exception):
        pass

    client = Mock(writable=True)
    if action == 'error':
        client.cancel.side_effect = ReservationError('offline', 'Could not cancel.')
    state = {}
    error = Mock()
    monkeypatch.setattr(ui.st, 'session_state', state)
    monkeypatch.setattr(ui.st, 'write', Mock())
    monkeypatch.setattr(ui.st, 'caption', Mock())
    monkeypatch.setattr(ui.st, 'columns', lambda *args: [nullcontext(), nullcontext()])
    monkeypatch.setattr(ui.st, 'button', lambda label, **kwargs: label == ('Keep reservation' if action == 'keep' else 'Confirm cancellation'))
    monkeypatch.setattr(ui.st, 'error', error)
    monkeypatch.setattr(ui.st, 'rerun', Mock(side_effect=Rerun))
    record = {'id': 'captured', 'owner_email': 'alice@example.org', 'start_at': '2030-01-07T09:15:00Z'}
    render = inspect.unwrap(ui.confirm_cancellation)
    if action == 'error':
        render(client, 'node', record, 'UTC')
        error.assert_called_once_with('Could not cancel.')
        assert 'reservation_notice' not in state
        ui.st.rerun.assert_not_called()
    else:
        with pytest.raises(Rerun):
            render(client, 'node', record, 'UTC')
    if action == 'keep':
        client.cancel.assert_not_called()
        assert not state
    else:
        client.cancel.assert_called_once_with('captured')
    if action == 'confirm':
        assert state['reservation_notice'] == 'Reservation cancelled.'
