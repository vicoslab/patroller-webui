"""Simple repeats follow the start date and reuse the elapsed duration."""
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest
from test_reservations import reservations_fixture, recurring_fixture, booking_widget


@pytest.mark.parametrize('choice,frequency,step', [
    ('Daily', 'daily', 'every day'), ('Weekly', 'weekly', 'every 7 days'),
    ('Every two weeks', 'biweekly', 'every 14 days'), ('Monthly', 'monthly', 'same day each month'),
])
def test_repeat_means_same_time_duration_without_weekday_picker(choice, frequency, step):
    app = AppTest.from_function(reservations_fixture).run()
    booking_widget(app, 'date_input', 'Start date', create=True).set_value(date(2030, 1, 7)).run()
    booking_widget(app, 'number_input', 'Start hour', create=True).set_value(9).run()
    booking_widget(app, 'number_input', 'Start minute', create=True).set_value(15).run()
    booking_widget(app, 'number_input', 'Duration (hours)', create=True).set_value(1.5).run()
    booking_widget(app, 'selectbox', 'Repeat', create=True).select(choice).run()
    assert not app.exception
    assert not any(x.label == 'Weekdays' for x in app.multiselect)
    until = booking_widget(app, 'date_input', 'Last repeat date', create=True)
    assert until.value > date(2030, 1, 7)
    add = next(x for x in app.get('expander') if x.label == 'Add reservation')
    captions = '\n'.join(x.value for x in add.get('caption'))
    assert step in captions and '09:15' in captions and '1.5 hours' in captions
    assert '366 days' not in captions and 'Ambiguous' not in captions
    until.set_value(date(2030, 3, 7))
    booking_widget(app, 'multiselect', 'GPUs', create=True).set_value(['uuid'])
    booking_widget(app, 'text_input', 'Owner email', create=True).set_value('alice@example.org')
    next(x for x in app.button if x.label == 'Add reservation').click().run()
    saved = app.session_state['created_fixture']
    assert saved['recurrence'] == dict(frequency=frequency, until='2030-03-07', timezone='Europe/Ljubljana',
                                       **({'weekdays': [0]} if frequency in ('weekly', 'biweekly') else {}))
    assert saved['start_at'] == '2030-01-07T08:15:00Z'
    assert saved['end_at'] == '2030-01-07T09:45:00Z'


def test_editing_uses_simple_start_weekday_without_compatibility_options():
    app = AppTest.from_function(recurring_fixture).run()
    assert not any(x.label == 'Weekdays' for x in app.multiselect)
    assert not app.checkbox
    next(x for x in app.button if x.label == 'Save changes').click().run()
    assert app.session_state['series_update'][1]['recurrence']['weekdays'] == [0]


def test_last_repeat_date_survives_repeat_off_and_on():
    app = AppTest.from_function(reservations_fixture).run()
    booking_widget(app, 'date_input', 'Start date', create=True).set_value(date(2030, 1, 7)).run()
    booking_widget(app, 'selectbox', 'Repeat', create=True).select('Weekly').run()
    booking_widget(app, 'date_input', 'Last repeat date', create=True).set_value(date(2030, 3, 15)).run()
    booking_widget(app, 'selectbox', 'Repeat', create=True).select('Does not repeat').run()
    assert not any(x.label == 'Last repeat date' for x in app.date_input)
    booking_widget(app, 'selectbox', 'Repeat', create=True).select('Weekly').run()
    assert booking_widget(app, 'date_input', 'Last repeat date', create=True).value == date(2030, 3, 15)


def precise_schedule_fixture():
    from webui_reservations import show_saved_schedule
    show_saved_schedule({'occurrences': [{'start_at': '2030-01-07T09:15:23.123456Z',
                                         'end_at': '2030-01-07T10:45:23.123456Z'}]}, 'UTC')


def test_saved_start_precision_is_not_hidden():
    app = AppTest.from_function(precise_schedule_fixture).run()
    assert not app.exception
    data = app.get('popover')[0].get('arrow_data_frame')[0].value
    assert data['Start (UTC)'].tolist() == ['2030-01-07 09:15:23.123456']
    assert data['Duration (hours)'].tolist() == [1.5]


def test_saved_schedule_lists_each_start_and_duration_not_date_ranges():
    app = AppTest.from_function(recurring_fixture).run()
    preview = next(x for x in app.get('popover') if x.proto.popover.label == 'Scheduled bookings (2)')
    table = preview.get('arrow_data_frame')[0].value
    assert list(table.columns) == ['Start (UTC)', 'Duration (hours)']
    assert table.iloc[:, 0].tolist() == ['2026-01-05 10:15', '2026-01-12 10:15']
    assert table['Duration (hours)'].tolist() == [49.5, 49.5]
    assert any('saved schedule' in x.value.lower() for x in preview.get('caption'))


def schedule_fixture(count):
    from webui_reservations import show_saved_schedule
    from datetime import datetime, timedelta, timezone
    start = datetime(2030, 1, 7, 9, 15, tzinfo=timezone.utc)
    windows = [{'start_at': (start + timedelta(days=i)).isoformat(),
                'end_at': (start + timedelta(days=i, hours=1.5)).isoformat()} for i in range(count)]
    show_saved_schedule({'occurrences': windows}, 'UTC')


@pytest.mark.parametrize('count', [1, 25])
def test_saved_schedule_explains_single_booking_and_does_not_hide_long_series(count):
    app = AppTest.from_function(schedule_fixture, args=(count,)).run()
    assert not app.exception
    preview = app.get('popover')[0]
    assert preview.proto.popover.label == f'Scheduled bookings ({count})'
    assert len(preview.get('arrow_data_frame')[0].value) == count
    if count == 1:
        assert any('only one booking' in x.value.lower() for x in preview.get('info'))
