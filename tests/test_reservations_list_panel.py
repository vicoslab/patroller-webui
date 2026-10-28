"""Reservations list panel order and same-rerun filtering."""
from streamlit.testing.v1 import AppTest
from test_reservations import reservations_fixture


def test_list_panel_opens_with_table_above_filters_and_before_add_edit():
    app = AppTest.from_function(reservations_fixture).run()
    assert not app.exception
    panels = app.get('expander')
    assert [p.label for p in panels] == ['Reservations list', 'Add reservation', 'Edit reservation']
    panel = panels[0]
    assert panel.proto.expanded
    assert not panels[2].proto.expanded
    children = list(panel.children.values())
    table_index = next(i for i, child in enumerate(children) if child.type == 'arrow_data_frame')
    filter_index = next(i for i, child in enumerate(children) if child.type == 'horizontal')
    assert table_index < filter_index
    assert [x.label for x in panel.get('multiselect')] == ['Filter GPUs', 'Filter owners', 'Filter status']
    assert [x.label for x in panel.get('date_input')] == ['Overlaps on or after', 'Overlaps on or before']
    assert [x.label for x in panel.get('button')] == ['Refresh']


def test_table_updates_without_filter_lag_and_refresh_retains_filters():
    app = AppTest.from_function(reservations_fixture).run()
    assert len(app.dataframe[0].value) == 1
    status = next(x for x in app.multiselect if x.label == 'Filter status')
    status.set_value(['Upcoming']).run()
    assert not app.exception
    assert len(app.dataframe[0].value) == 0
    assert any('No reservations match' in x.value for x in app.info)
    assert not any(x.label == 'Reservation to manage' for x in app.selectbox)
    next(x for x in app.button if x.label == 'Refresh').click().run()
    assert not app.exception
    assert next(x for x in app.multiselect if x.label == 'Filter status').value == ['Upcoming']
    assert len(app.dataframe[0].value) == 0
    next(x for x in app.multiselect if x.label == 'Filter status').set_value([]).run()
    assert len(app.dataframe[0].value) == 1
    assert any(x.label == 'Reservation to manage' for x in app.selectbox)


def empty_calendar_fixture():
    from unittest.mock import patch
    from webui_reservations import run_reservations

    class Patroller:
        cfg = {'servers': [{'name': 'node', 'url': 'http://127.0.0.1', 'reservation_token': 'fixture'}]}
        def __init__(self, *args): pass
        def __len__(self): return 1
        def __iter__(self):
            return iter([{'name': 'node', 'data': {}, 'devs': {'uuid': {'number': 0, 'name': 'GPU'}}}])

    with patch('webui_reservations.Patroller', Patroller), patch('webui_reservations.ReservationClient') as client:
        client.return_value.writable = True
        client.return_value.list.return_value = []
        run_reservations()


def test_empty_calendar_retains_open_list_panel_and_refresh():
    app = AppTest.from_function(empty_calendar_fixture).run()
    assert not app.exception
    assert [x.label for x in app.get('expander')] == ['Reservations list', 'Add reservation']
    panel = app.get('expander')[0]
    assert panel.proto.expanded
    assert any('Calendar is empty' in x.value for x in panel.get('info'))
    assert [x.label for x in panel.get('button')] == ['Refresh']
    next(x for x in panel.get('button') if x.label == 'Refresh').click().run()
    assert not app.exception
