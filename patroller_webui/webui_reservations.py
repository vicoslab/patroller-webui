import json
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import streamlit as st

from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH
from patroller_webui.reservations import (ReservationClient, ReservationError, make_payload,
                                          parse_time, reservation_status, overlaps_days)


def gpu_label(uuid, devices):
    device = devices.get(uuid)
    return f"GPU {device['number']} — {device['name']}" if device else uuid


def local_datetime(value, zone):
    return parse_time(value).astimezone(ZoneInfo(zone)).replace(tzinfo=None)


def booking_form(client, devices, config, zone, server_name, record=None):
    edit = record is not None
    now = datetime.now(ZoneInfo(zone)).replace(tzinfo=None, second=0, microsecond=0)
    start = local_datetime(record['start_at'], zone) if edit else now
    end = local_datetime(record['end_at'], zone) if edit else now + timedelta(hours=1)
    users = config.get('reservation_users') or []
    missing_gpus = set((record or {}).get('gpu_uuids', [])) - set(devices)
    if missing_gpus:
        st.warning('Some booked GPUs are missing from device metadata; editing is unavailable.')
    scope = json.dumps([server_name, record['id'] if edit else None], ensure_ascii=True)
    key = lambda field: f'booking:{scope}:{field}'
    with st.form(key('edit' if edit else 'add')):
        ids = list(devices)
        selected = st.multiselect('GPUs', ids, default=[x for x in (record or {}).get('gpu_uuids', []) if x in devices],
                                  format_func=lambda x: gpu_label(x, devices), key=key('gpus'))
        existing_owner = (record or {}).get('owner_email', '')
        if users:
            emails = [u['email'] for u in users]
            if existing_owner and existing_owner not in emails:
                emails.append(existing_owner)
            names = {u['email']: u.get('name', u['email']) for u in users}
            owner = st.selectbox('Owner', emails, index=emails.index(existing_owner) if existing_owner in emails else 0,
                                 format_func=lambda x: f"{names.get(x, x)} ({x})" if names.get(x, x) != x else x, key=key('owner'))
        else:
            owner = st.text_input('Owner email', value=existing_owner, key=key('owner'))
        st.caption(f'Local time: {zone}. Ambiguous and nonexistent daylight saving times are rejected.')
        a, b = st.columns(2)
        with a:
            start_date = st.date_input('Start date', value=start.date())
            start_time = st.time_input('Start time', value=start.time(), step=60)
        with b:
            end_date = st.date_input('End date', value=end.date())
            end_time = st.time_input('End time', value=end.time(), step=60)
        note = st.text_area('Note', value=(record or {}).get('note', ''), key=key('note'))
        st.warning('Warning: an immediate reservation kills non-owner GPU processes when kill enforcement is enabled.')
        submitted = st.form_submit_button('Save changes' if edit else 'Add reservation', disabled=not client.writable or not devices or bool(missing_gpus))
    if submitted:
        try:
            payload = make_payload(selected, owner, datetime.combine(start_date, start_time), datetime.combine(end_date, end_time), note, zone)
            if edit:
                client.update(record['id'], payload)
            else:
                client.create(payload)
            st.session_state['reservation_notice'] = 'Reservation saved.'
            st.rerun()
        except (ValueError, ReservationError) as exc:
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
    if st.button('Refresh reservations'):
        st.rerun()
    try:
        records = client.list()
    except ReservationError as exc:
        st.error(f'{exc.state.capitalize()}: {exc}')
        return
    # Device metadata comes from the existing monitor, not the reservation API.
    current = next((s for s in patroller if s['name'] == selected), None)
    devices = (current or {}).get('devs') or {}
    if not current or current['data'] is None:
        st.warning('Server monitoring is offline; GPU selection is unavailable.')
    elif not devices:
        st.warning('GPU device information is unavailable.')
    if not records:
        st.info('Calendar is empty.')
    else:
        gpu_options = sorted({g for r in records for g in r['gpu_uuids']})
        a, b, c = st.columns(3)
        with a:
            gpu_filter = st.multiselect('Filter GPUs', gpu_options, format_func=lambda x: gpu_label(x, devices))
        with b:
            owner_filter = st.multiselect('Filter owners', sorted({r['owner_email'] for r in records}))
        with c:
            status_filter = st.multiselect('Filter status', ['Active', 'Upcoming', 'Past'])
        a, b = st.columns(2)
        with a:
            after = st.date_input('Overlaps on or after', value=None)
        with b:
            before = st.date_input('Overlaps on or before', value=None)
        filtered = []
        for r in records:
            if gpu_filter and not set(gpu_filter).intersection(r['gpu_uuids']): continue
            if owner_filter and r['owner_email'] not in owner_filter: continue
            if status_filter and reservation_status(r) not in status_filter: continue
            if not overlaps_days(r, after, before, zone): continue
            filtered.append(r)
        st.dataframe([{'GPUs': ', '.join(gpu_label(g, devices) for g in r['gpu_uuids']), 'Owner': r['owner_email'],
                       'Start': local_datetime(r['start_at'], zone).strftime('%Y-%m-%d %H:%M'),
                       'End': local_datetime(r['end_at'], zone).strftime('%Y-%m-%d %H:%M'),
                       'Status': reservation_status(r), 'Note': r.get('note', '')} for r in filtered], use_container_width=True, hide_index=True)
        if not filtered:
            st.info('No reservations match these filters.')
        if filtered:
            chosen = st.selectbox('Reservation to manage', filtered,
                                  format_func=lambda r: f"{r['owner_email']} — {local_datetime(r['start_at'], zone):%Y-%m-%d %H:%M} — {r['id']}")
            with st.expander('Edit reservation'):
                booking_form(client, devices, config, zone, selected, chosen)
            with st.expander('Cancel reservation'):
                cancel_scope = json.dumps([selected, chosen['id']], ensure_ascii=True)
                with st.form(f'cancel:{cancel_scope}'):
                    confirm = st.checkbox('Confirm cancellation of this reservation', key=f'cancel-confirm:{cancel_scope}')
                    cancel = st.form_submit_button('Cancel reservation', disabled=not client.writable)
                if cancel:
                    if not confirm:
                        st.error('Confirm cancellation first.')
                    else:
                        try:
                            client.cancel(chosen['id'])
                            st.session_state['reservation_notice'] = 'Reservation cancelled.'
                            st.rerun()
                        except ReservationError as exc:
                            st.error(str(exc))
    with st.expander('Add reservation', expanded=not records):
        booking_form(client, devices, config, zone, selected)
