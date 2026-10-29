"""Session-only reservation credentials; never fall back to service config."""
import streamlit as st

from patroller_webui.reservations import ReservationClient, ReservationError


_TOKEN = 'reservation_browser_token'
_DRAFT = 'reservation_write_token_draft'
_ERROR = 'reservation_write_token_error'
_INVALID = 'Invalid write token. Enter a single nonempty printable ASCII token (maximum 4096 characters).'


def _valid_token(value):
    return (isinstance(value, str) and 0 < len(value) <= 4096
            and all(33 <= ord(char) <= 126 for char in value))


def capture_url_token():
    """Consume only write-token before navigation can discard query parameters."""
    values = st.query_params.get_all('write-token')
    if not values:
        return
    del st.query_params['write-token']
    st.session_state.pop(_TOKEN, None)
    st.session_state[_DRAFT] = ''
    if len(values) == 1 and _valid_token(values[0]):
        st.session_state[_TOKEN] = values[0]
        st.session_state.pop(_ERROR, None)
    else:
        st.session_state[_ERROR] = _INVALID


def _submit_token():
    candidate = st.session_state.get(_DRAFT, '')
    st.session_state[_DRAFT] = ''
    st.session_state.pop(_TOKEN, None)
    if _valid_token(candidate):
        st.session_state[_TOKEN] = candidate
        st.session_state.pop(_ERROR, None)
    else:
        st.session_state[_ERROR] = _INVALID


def configure_write_access(server, config):
    """Return a client writable only after this node verifies this session token."""
    candidate = st.session_state.get(_TOKEN, '')
    # Explicitly suppress both node and global legacy credentials for pages.
    browser_server = dict(server, reservation_token=candidate)
    client = ReservationClient(browser_server, dict(config))
    verified = False
    if candidate:
        try:
            verified = client.verify_write_access() is True
        except ReservationError:
            pass  # Never display server/exception details containing a credential.
    if verified:
        return client
    client.token = ''
    with st.form('reservation-write-access', clear_on_submit=True):
        st.caption('Read-only: enter a write token to unlock reservations for this browser session.')
        if st.session_state.get(_ERROR):
            st.error(st.session_state[_ERROR])
        elif candidate:
            st.error('Write access could not be verified on this server. Check the token or retry.')
        token_col, unlock_col = st.columns([4, 1.3], vertical_alignment='bottom')
        with token_col:
            st.text_input('Write token', type='password', key=_DRAFT)
        with unlock_col:
            st.form_submit_button('Unlock reservations', on_click=_submit_token, use_container_width=True)
    return client
