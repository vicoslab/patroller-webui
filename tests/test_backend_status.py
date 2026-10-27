from patroller_webui.reservations import gpu_state


def test_unavailable_calendar_is_not_advertised_as_free():
    info = {'claim': {}, 'active_reservation': None, 'next_reservation': None,
            'reservation_state': 'unavailable'}
    assert gpu_state(info) == ('UNKNOWN', False)


def test_disabled_calendar_keeps_unreserved_gpu_available():
    info = {'claim': {}, 'active_reservation': None, 'next_reservation': None,
            'reservation_state': 'disabled'}
    assert gpu_state(info) == ('FREE', True)
