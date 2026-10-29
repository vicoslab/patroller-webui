import json
import sys
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH
from patroller_webui.reservations import (ReservationClient, ReservationError, make_duration_payload,
                                          parse_time, reservation_status, overlaps_days)
from patroller_webui.owner_suggestions import suggestions
from patroller_webui.identity import owner_key, owner_label


def gpu_label(uuid, devices):
    device = devices.get(uuid)
    return f"GPU {device['number']} — {device['name']}" if device else uuid


def local_datetime(value, zone):
    return parse_time(value).astimezone(ZoneInfo(zone)).replace(tzinfo=None)


REPEAT_OPTIONS = {'Does not repeat': None, 'Daily': 'daily', 'Weekly': 'weekly',
                  'Every two weeks': 'biweekly', 'Monthly': 'monthly'}

def repeat_summary(record):
    rule = record.get('recurrence')
    if not rule:
        return 'Does not repeat'
    label = next((label for label, value in REPEAT_OPTIONS.items() if value == rule.get('frequency')), rule.get('frequency', ''))
    count = len(record.get('occurrences', []))
    return f"{label} until {rule.get('until', '')} · {count} {'booking' if count == 1 else 'bookings'}"


def show_saved_schedule(record, zone):
    windows = record.get('occurrences') or []
    if not windows:
        return
    with st.popover(f'Scheduled bookings ({len(windows)})'):
        st.caption('Saved schedule: each row is one booking start and its duration. Save changes to update this list.')
        if len(windows) == 1:
            st.info('This series has only one booking. Choose a later Last repeat date and save to include more repeats.')
        starts = [local_datetime(w['start_at'], zone) for w in windows]
        st.dataframe([{f'Start ({zone})': start.isoformat(sep=' ', timespec='microseconds' if start.microsecond else 'seconds' if start.second else 'minutes'),
                       'Duration (hours)': (parse_time(w['end_at']) - parse_time(w['start_at'])).total_seconds() / 3600}
                      for w, start in zip(windows, starts)], hide_index=True, use_container_width=True)


def booking_form(client, devices, config, zone, server_name, record=None, owner_options=None):
    edit = record is not None
    rule = (record or {}).get('recurrence') or {}
    zone = rule.get('timezone', zone)
    scope = json.dumps([server_name, record['id'] if edit else None], ensure_ascii=True)
    key = lambda field: f'booking:{scope}:{field}'
    if edit:
        start = local_datetime(record['start_at'], zone)
    else:
        if key('draft-start') not in st.session_state:
            st.session_state[key('draft-start')] = datetime.now(ZoneInfo(zone)).replace(tzinfo=None, second=0, microsecond=0)
        start = st.session_state[key('draft-start')]
    duration = ((parse_time(record['end_at']) - parse_time(record['start_at'])).total_seconds() / 3600) if edit else 1.0

    missing_gpus = set((record or {}).get('gpu_uuids', [])) - set(devices)
    if missing_gpus:
        st.warning('Some booked GPUs are missing from device metadata; editing is unavailable.')
    if edit and rule:
        st.caption('Changes apply to the entire series.')
    repeat_default = next((label for label, value in REPEAT_OPTIONS.items() if value == rule.get('frequency')), 'Does not repeat')
    # Only memory/cache lookup here: optional history discovery runs in one daemon.
    if owner_options is None:
        owner_options = suggestions([record] if edit else [], config, history_path='')
    owners = {owner_key({'owner_email': item['email'], 'owner_name': item.get('name', ''),
                         **({'owner_type': 'name'} if item.get('owner_type') == 'name' else {})}): item
              for item in owner_options}
    owners.pop('', None)
    existing_owner = (record or {}).get('owner_email', '')
    existing_key = owner_key(record or {})
    if edit:
        # Always retain this booking even when it lies outside the sampled hints.
        owners[existing_key] = {'email': existing_owner, 'name': record.get('owner_name', ''),
                                **({'owner_type': 'name'} if record.get('owner_type') == 'name' else {})}
    previous = st.session_state.get(key('selected-owner'), {})
    default_owner = st.session_state.get(key('owner-choice'), previous.get('key', existing_key if edit else '__custom__'))
    if default_owner != '__custom__' and default_owner not in owners:
        owners[default_owner] = previous.get('item', {'email': default_owner, 'name': ''})
    def choice_label(value):
        if value == '__custom__':
            return 'New / custom owner'
        item = owners[value]
        if item.get('owner_type') == 'name':
            return f"Container: {item['name']}"
        return f"{item['name']} ({item['email']})" if item.get('name') else item['email']
    choices = ['__custom__'] + sorted(owners)
    # Keep the row outside the submit form so Owner/Repeat reveal controls live.
    owner_col, date_col, hour_col, minute_col, duration_col, repeat_col = st.columns([3.2, 1.6, 1, 1, 1.5, 1.9])
    with owner_col:
        owner_choice = st.selectbox('Owner', choices, index=choices.index(default_owner),
                                    key=key('owner-choice'),
                                    format_func=choice_label,
                                    help='Known owners are suggestions only. Choose New / custom owner to enter an email or exact container name.')
        st.session_state[key('selected-owner')] = {'key': owner_choice, 'item': owners.get(owner_choice, {})}
    with date_col:
        start_date = st.date_input('Start date', value=start.date(), key=key('start-date'))
    with hour_col:
        hour = st.number_input('Start hour', min_value=0, max_value=23, value=start.hour, step=1, key=key('hour'))
    with minute_col:
        minute = st.number_input('Start minute', min_value=0, max_value=59, value=start.minute, step=1, key=key('minute'))
    with duration_col:
        duration_value = st.number_input('Duration (hours)', min_value=min(0.25, duration), max_value=max(8784.0, duration), value=float(duration), step=0.25, format='%.12g', key=key('duration'))
    with repeat_col:
        repeat = st.selectbox('Repeat', list(REPEAT_OPTIONS), index=list(REPEAT_OPTIONS).index(repeat_default), key=key('repeat'))
    # Persist custom drafts independently of conditional widget cleanup.
    if key('owner') in st.session_state:
        st.session_state[key('custom-email')] = st.session_state[key('owner')]
    if key('owner-name') in st.session_state:
        st.session_state[key('custom-name')] = st.session_state[key('owner-name')]
    if key('container-name') in st.session_state:
        st.session_state[key('custom-container-name')] = st.session_state[key('container-name')]
    if key('identity-mode') in st.session_state:
        st.session_state[key('custom-identity-mode')] = st.session_state[key('identity-mode')]
    owner_type = None
    if owner_choice == '__custom__':
        modes = ['Email', 'Container name']
        default_mode = st.session_state.get(key('custom-identity-mode'), 'Container name' if (record or {}).get('owner_type') == 'name' else 'Email')
        mode = st.selectbox('Owner identity', modes, index=modes.index(default_mode), key=key('identity-mode'))
        if mode == 'Container name':
            owner, owner_type = '', 'name'
            owner_name = st.text_input('Container name', value=st.session_state.get(key('custom-container-name'), (record or {}).get('owner_name', '') if (record or {}).get('owner_type') == 'name' else ''),
                                       key=key('container-name'), max_chars=200,
                                       help='Required: exact ccc-user.name label, case-sensitive. Trusted lab identity, not an authenticated human.')
        else:
            email_col, name_col = st.columns(2)
            def changed_email():
                st.session_state[key('owner-name')] = ''
                st.session_state[key('custom-name')] = ''
            with email_col:
                owner = st.text_input('Owner email', value=st.session_state.get(key('custom-email'), existing_owner),
                                      key=key('owner'), placeholder='person@example.org', on_change=changed_email,
                                      help='Required: enter the email used for your CCC account/container. You can enter any valid email.')
            with name_col:
                owner_name = st.text_input('Owner name (optional)', value=st.session_state.get(key('custom-name'), (record or {}).get('owner_name', '') if (record or {}).get('owner_type') != 'name' else ''),
                                           key=key('owner-name'), max_chars=200,
                                           help='Display name only. Ownership and process permissions always use Owner email.')
    else:
        item = owners[owner_choice]
        owner, owner_name, owner_type = item['email'], item.get('name', ''), item.get('owner_type')
    st.caption(f'Times shown in {zone}.')
    until = None
    # Keep the date draft even when Repeat temporarily hides its widget.
    if key('until') in st.session_state:
        st.session_state[key('default-until')] = st.session_state[key('until')]
    frequency = REPEAT_OPTIONS[repeat]
    if frequency:
        interval = {'daily': 'every day', 'weekly': 'every 7 days', 'biweekly': 'every 14 days',
                    'monthly': 'on the same day each month'}[frequency]
        st.caption(f'Repeats {interval} at {hour:02d}:{minute:02d}, for {duration_value:g} hours each time, starting {start_date:%Y-%m-%d}.')
        if frequency == 'monthly' and start_date.day >= 29:
            st.caption(f'Months without day {start_date.day} have no booking; the next booking keeps day {start_date.day}.')
        if key('default-until') not in st.session_state:
            st.session_state[key('default-until')] = datetime.fromisoformat(rule['until']).date() if rule.get('until') else start_date + timedelta(days=90)
        until = st.date_input('Last repeat date', value=st.session_state[key('default-until')], key=key('until'),
                              help='The last date on which a booking may start, not when a booking ends. Each booking lasts Duration (hours). Choose up to 366 days after the start date.')
        st.caption('Last repeat date stops new bookings after that date; it does not change how long each booking lasts.')
    with st.form(key('edit' if edit else 'add')):
        ids = list(devices)
        selected = st.multiselect('GPUs', ids, default=[x for x in (record or {}).get('gpu_uuids', []) if x in devices],
                                  format_func=lambda x: gpu_label(x, devices), key=key('gpus'))

        note = st.text_area('Note', value=(record or {}).get('note', ''), key=key('note'))
        st.warning('Warning: an immediate reservation kills non-owner GPU processes when kill enforcement is enabled.')
        submitted = st.form_submit_button('Save changes' if edit else 'Add reservation', disabled=not client.writable or not devices or bool(missing_gpus))
    if submitted:
        try:
            recurrence = None
            if until is not None:
                if not start_date <= until <= start_date + timedelta(days=366):
                    raise ValueError('Last repeat date must be on or after Start date and no more than 366 days later.')
                recurrence = {'frequency': frequency, 'until': until.isoformat(), 'timezone': zone}
                if frequency in ('weekly', 'biweekly'):
                    recurrence['weekdays'] = [start_date.weekday()]
            seconds = (start.second, start.microsecond) if edit and (start_date, hour, minute) == (start.date(), start.hour, start.minute) else (0, 0)
            payload = make_duration_payload(selected, owner, datetime.combine(start_date, time(hour, minute, *seconds)), duration_value, note, zone, recurrence, original_duration=(parse_time(record['end_at']) - parse_time(record['start_at'])) if edit and duration_value == duration else None, owner_name=owner_name, owner_type=owner_type)
            if edit:
                client.update(record['id'], payload)
            else:
                client.create(payload)
            end = parse_time(payload['end_at']).astimezone(ZoneInfo(zone))
            st.session_state['reservation_notice'] = f"Reservation saved. Ends {end:%Y-%m-%d %H:%M:%S %Z} ({zone})."
            st.rerun()
        except (ValueError, ReservationError) as exc:
            st.error(str(exc))


@st.experimental_dialog('Cancel reservation?')
def confirm_cancellation(client, server_name, record, zone):
    """Only the modal's explicit confirmation may cancel the captured booking."""
    scope = json.dumps([server_name, record['id']], ensure_ascii=True)
    st.write(owner_label(record))
    st.caption(f"Starts {local_datetime(record['start_at'], zone):%Y-%m-%d %H:%M} ({zone})")
    st.write('This will cancel the entire recurring series.' if record.get('recurrence') else 'This will remove this reservation.')
    keep_col, confirm_col = st.columns(2)
    with keep_col:
        if st.button('Keep reservation', key=f'cancel-keep:{scope}', use_container_width=True):
            st.rerun()
    with confirm_col:
        if st.button('Confirm cancellation', key=f'cancel-confirm:{scope}', type='primary', use_container_width=True, disabled=not client.writable):
            try:
                client.cancel(record['id'])
                st.session_state['reservation_notice'] = 'Reservation cancelled.'
                st.rerun()
            except ReservationError as exc:
                st.error(str(exc))


def run_reservations():
    st.title('Reservations')
    st.caption('Trusted-lab management: anyone with the write credential can manage bookings for any owner. Occupancy is independent of reservations.')
    patroller = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)
    config = patroller.cfg
    zone = config.get('timezone', 'Europe/Ljubljana')
    try:
        ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        st.error('Configured timezone is invalid.')
        return
    if not len(patroller):
        st.info('No servers configured.')
        return
    if st.session_state.get('reservation_notice'):
        st.success(st.session_state.pop('reservation_notice'))
    st.caption(f'Times shown in {zone}.')
    servers = {s['name']: s for s in config['servers']}
    selected = st.selectbox('Server', list(servers))
    server = servers[selected]
    client = ReservationClient(server, config)
    if not client.writable:
        st.info('Read-only: no reservation write credential is configured.')
    try:
        records = client.list()
    except ReservationError as exc:
        st.error(f'{exc.state.capitalize()}: {exc}')
        if st.button('Refresh'):
            st.rerun()
        return
    # Device metadata comes from the existing monitor, not the reservation API.
    current = next((s for s in patroller if s['name'] == selected), None)
    devices = (current or {}).get('devs') or {}
    if not current or current['data'] is None:
        st.warning('Server monitoring is offline; GPU selection is unavailable.')
    elif not devices:
        st.warning('GPU device information is unavailable.')
    history_path = config.get('reservation_history_path') or (sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH)
    users = []
    data = (current or {}).get('data')
    for info in data.values() if isinstance(data, dict) else ():
        claim = info.get('claim') if isinstance(info, dict) else None
        if not isinstance(claim, dict):
            continue
        claim_users = claim.get('users')
        if not isinstance(claim_users, list):
            claim_users = [claim.get('user')]
        users.extend(user for user in claim_users if isinstance(user, dict))
    owner_options = suggestions(records, config, history_path, users)
    filtered = []
    with st.expander('Reservations list', expanded=True):
        if not records:
            st.info('Calendar is empty.')
            if st.button('Refresh'):
                st.rerun()
        else:
            # Reserve the table's position above the controls, then populate it
            # using this rerun's filter values rather than the previous ones.
            table = st.empty()
            gpu_options = sorted({g for r in records for g in r['gpu_uuids']})
            gpu_col, owner_col, status_col, after_col, before_col, refresh_col = st.columns([2, 2, 1.5, 1.8, 1.8, 1], vertical_alignment='bottom')
            with gpu_col:
                gpu_filter = st.multiselect('Filter GPUs', gpu_options, format_func=lambda x: gpu_label(x, devices))
            with owner_col:
                owner_records = {owner_key(r): r for r in records}
                owner_filter = st.multiselect('Filter owners', sorted(owner_records), format_func=lambda value: owner_label(owner_records[value]))
            with status_col:
                status_filter = st.multiselect('Filter status', ['Active', 'Upcoming', 'Past'])
            with after_col:
                after = st.date_input('Overlaps on or after', value=None)
            with before_col:
                before = st.date_input('Overlaps on or before', value=None)
            with refresh_col:
                if st.button('Refresh', use_container_width=True):
                    st.rerun()
            for r in records:
                if gpu_filter and not set(gpu_filter).intersection(r['gpu_uuids']): continue
                if owner_filter and owner_key(r) not in owner_filter: continue
                if status_filter and reservation_status(r) not in status_filter: continue
                if not overlaps_days(r, after, before, zone): continue
                filtered.append(r)
            table.dataframe([{'GPUs': ', '.join(gpu_label(g, devices) for g in r['gpu_uuids']), 'Owner': owner_label(r), 'Owner email': r['owner_email'],
                              'Owner name': r.get('owner_name', ''),
                              'Start': local_datetime(r['start_at'], zone).strftime('%Y-%m-%d %H:%M'),
                              'End': local_datetime(r['end_at'], zone).strftime('%Y-%m-%d %H:%M'),
                              'Status': reservation_status(r), 'Repeat': repeat_summary(r), 'Note': r.get('note', '')} for r in filtered], use_container_width=True, hide_index=True)
            if not filtered:
                st.info('No reservations match these filters.')
    with st.expander('Add reservation', expanded=not records):
        booking_form(client, devices, config, zone, selected, owner_options=owner_options)
    if filtered:
        with st.expander('Edit reservation', expanded=False):
            selection_col, cancel_col = st.columns([5, 1.2], vertical_alignment='bottom')
            with selection_col:
                chosen = st.selectbox('Reservation to manage', filtered,
                                      format_func=lambda r: f"{owner_label(r)} — {local_datetime(r['start_at'], zone):%Y-%m-%d %H:%M} — {r['id']}")
            with cancel_col:
                cancel_scope = json.dumps([selected, chosen['id']], ensure_ascii=True)
                if st.button('Cancel reservation', key=f'cancel-open:{cancel_scope}', disabled=not client.writable, use_container_width=True):
                    confirm_cancellation(client, selected, chosen, zone)
            show_saved_schedule(chosen, (chosen.get('recurrence') or {}).get('timezone', zone))
            booking_form(client, devices, config, zone, selected, chosen, owner_options=owner_options)
