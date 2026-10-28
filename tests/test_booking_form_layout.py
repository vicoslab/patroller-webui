"""Compact shared booking row, with immediate recurrence control updates."""
import pytest
from streamlit.testing.v1 import AppTest


def booking_fixture(configured_owner, edit):
    from webui_reservations import booking_form

    class Client:
        writable = True

    config = {'reservation_users': [{'email': 'alice@example.org', 'name': 'Alice'}]} if configured_owner else {}
    record = {'id': 'existing', 'owner_email': 'alice@example.org', 'gpu_uuids': ['uuid'],
              'start_at': '2030-01-07T09:15:00Z', 'end_at': '2030-01-07T10:45:00Z'} if edit else None
    booking_form(Client(), {'uuid': {'number': 0, 'name': 'GPU'}}, config, 'UTC', 'node', record)


@pytest.mark.parametrize('configured_owner', [True, False])
@pytest.mark.parametrize('edit', [True, False])
def test_booking_controls_share_one_weighted_row(configured_owner, edit):
    app = AppTest.from_function(booking_fixture, args=(configured_owner, edit)).run()
    assert not app.exception
    expected = ['Owner', 'Start date', 'Start hour',
                'Start minute', 'Duration (hours)', 'Repeat']
    rows = []
    for row in app.get('horizontal'):
        columns = list(row.children.values())
        labels = [[child.label for child in column.children.values() if hasattr(child, 'label')]
                  for column in columns]
        if labels == [[label] for label in expected]:
            rows.append(columns)
    assert len(rows) == 1, 'Owner, start date/hour/minute, duration and Repeat must share one row'
    weights = [column.proto.weight for column in rows[0]]
    assert weights[0] > max(weights[1:]), 'Owner must have the most space'
    assert weights[2] < weights[1] and weights[3] < weights[1], 'Hour/minute should stay compact'


def test_calendar_filters_and_refresh_share_one_row():
    from test_reservations import reservations_fixture

    app = AppTest.from_function(reservations_fixture).run()
    assert not app.exception
    expected = ['Filter GPUs', 'Filter owners', 'Filter status', 'Overlaps on or after',
                'Overlaps on or before', 'Refresh']
    rows = []
    for row in app.get('horizontal'):
        columns = list(row.children.values())
        labels = [[child.label for child in column.children.values() if hasattr(child, 'label')]
                  for column in columns]
        if labels == [[label] for label in expected]:
            rows.append(columns)
    assert len(rows) == 1, 'All five filters and Refresh must share one row'
    next(x for x in app.button if x.label == 'Refresh').click().run()
    assert not app.exception


def test_inline_repeat_updates_controls_without_discarding_booking_values():
    app = AppTest.from_function(booking_fixture, args=(True, False)).run()
    next(x for x in app.number_input if x.label == 'Duration (hours)').set_value(1.5).run()
    next(x for x in app.number_input if x.label == 'Start hour').set_value(9).run()
    next(x for x in app.number_input if x.label == 'Start minute').set_value(15).run()
    next(x for x in app.selectbox if x.label == 'Repeat').select('Weekly').run()
    assert not app.exception
    assert any(x.label == 'Last repeat date' for x in app.date_input)
    assert not any(x.label == 'Weekdays' for x in app.multiselect)
    values = {x.label: x.value for x in app.number_input}
    assert values == {'Start hour': 9, 'Start minute': 15, 'Duration (hours)': 1.5}


def test_add_panel_precedes_reservation_selector():
    from test_reservations import reservations_fixture

    app = AppTest.from_function(reservations_fixture).run()
    children = list(app.main.children.values())
    add_index = next(i for i, x in enumerate(children) if x.type == 'expander' and x.label == 'Add reservation')
    edit_index = next(i for i, x in enumerate(children) if x.type == 'expander' and x.label == 'Edit reservation')
    assert add_index < edit_index
    edit = children[edit_index]
    assert not edit.proto.expanded, 'Edit reservation should start closed'
    first_child = next(iter(edit.children.values()))
    assert first_child.type == 'horizontal'
    assert [x.label for x in first_child.get('selectbox')] == ['Reservation to manage']
    assert [x.label for x in first_child.get('button')] == ['Cancel reservation']
    assert not any(x.type == 'selectbox' and x.label == 'Reservation to manage' for x in children)


def test_inline_cancellation_opens_confirmation_dialog_before_deleting():
    from test_reservations import reservations_fixture

    app = AppTest.from_function(reservations_fixture).run()
    assert not app.exception
    assert not any(x.label == 'Cancel reservation' for x in app.get('expander'))
    edit = next(x for x in app.get('expander') if x.label == 'Edit reservation')
    assert {x.label for x in edit.get('button')} == {'Save changes', 'Cancel reservation'}
    assert len(edit.get('form')) == 1
    assert not app.checkbox
    next(x for x in edit.get('button') if x.label == 'Cancel reservation').click().run()
    assert not app.exception
    assert any(x.label == 'Confirm cancellation' for x in app.button)
    assert 'cancelled_fixture' not in app.session_state
    assert 'updated_fixture' not in app.session_state
    next(x for x in app.button if x.label == 'Keep reservation').click().run()
    assert 'cancelled_fixture' not in app.session_state
    assert not any(x.label == 'Confirm cancellation' for x in app.button)
    assert 'updated_fixture' not in app.session_state


def test_add_panel_remains_available_when_no_reservations_match():
    from test_reservations import reservations_fixture

    app = AppTest.from_function(reservations_fixture).run()
    next(x for x in app.multiselect if x.label == 'Filter status').set_value(['Upcoming']).run()
    assert not app.exception
    assert any(x.label == 'Add reservation' for x in app.get('expander'))
    assert not any(x.label == 'Reservation to manage' for x in app.selectbox)
