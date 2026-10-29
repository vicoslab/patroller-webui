import sys, time

import streamlit as st

from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH, format_user_details, get_user_display_name
from patroller_webui.reservations import gpu_state, parse_time, reservation_countdown
from zoneinfo import ZoneInfo
from patroller_webui.identity import owner_label, identity_email

def to_gigabytes(memory_mib):
    return "{0} GB".format(int(int(memory_mib.split()[0]) / 1024))


def run_dashboard():
    pattroler = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)

    if len(pattroler) <= 0:
        st.error("No servers found in config or missing config file (should be provided as cmd or in '%s')" % __DEFAULT_CONFIG_PATH)
        return
 
    show_men_use = st.sidebar.checkbox("Show GPU memory utilization", value=True)
    show_cpu_use = st.sidebar.checkbox("Show GPU processor utilization",value=False)
    show_temp = st.sidebar.checkbox("Show GPU temperature",value=False)
    show_json = st.sidebar.checkbox("Show raw info",value=False)
    show_gpu_id = st.sidebar.checkbox("Show GPU ID instead of index",value=False)
    unordered_list = st.sidebar.checkbox("Unordered list",value=False)

    total_info = st.empty()
    st.button("Refresh")

    num_metrics = ((show_cpu_use or show_men_use) + show_temp)

    total = 0
    total_available = 0
    for server_cfg in pattroler:
        server_name = server_cfg['name']
        server_url = server_cfg['url']
        gpu_data = server_cfg['data']
        gpu_devs = server_cfg['devs']
        
        if gpu_data is None:
            with st.expander(server_name,expanded=True):
                st.error("Unable to retrieve server status")
            continue

        with st.expander(server_name,expanded=True):
            cols_title = st.columns(len(gpu_data))
            cols_metrics = st.columns(len(gpu_data)* max(1,num_metrics))
            cols_info = st.columns(len(gpu_data))
            for gpu_index,(gpu_id,gpu_info) in enumerate(gpu_data.items()):
                
                gpu_dev = gpu_devs[gpu_id]

                disply_index = gpu_dev['number']

                if unordered_list:
                    disply_index = gpu_index

                with cols_title[disply_index]:
                    if show_gpu_id:
                        st.write(gpu_id)
                    else:
                        st.write("GPU %s %d" % (server_name,disply_index))

                    name = gpu_dev['name']
                    name = name.replace("NVIDIA","")
                    name = name.replace("GeForce","")
                    name = name.replace("Quadro","")

                    st.caption("{0} - {1}".format(name, to_gigabytes(gpu_dev['total_mem'])))

                metric_idx = 0
                if show_men_use or show_cpu_use:
                    with cols_metrics[disply_index * num_metrics + metric_idx]:
                        util_str = []
                        util_val = []
                        if show_men_use:
                            util_val.append(str(gpu_info['mem']))
                            util_str.append("MEM")
                        if show_cpu_use:
                            util_val.append(str(gpu_info['sm']))
                            util_str.append("CPU")

                        st.metric("%s utilization" % "/".join(util_str), '%s %%' % "/".join(util_val))
                        metric_idx += 1
                if show_temp:
                    with cols_metrics[disply_index * num_metrics + metric_idx]:
                        st.metric("Temperature", '%d °C' % gpu_info['gtemp'])
                        metric_idx += 1

                with cols_info[disply_index]:
                    claim = gpu_info.get('claim') or {}
                    claim_age_seconds = claim.get('age', 0)
                    claim_age = time.strftime('%Mm %Ssec', time.gmtime(claim_age_seconds))
                    
                    if claim_age_seconds > 60*60:
                        claim_age = '%dh %s' % (int(claim_age_seconds/(60*60)), claim_age)
                        
                    active = gpu_info.get('active_reservation')
                    claim_user = claim.get('user')
                    if not active:
                        if claim_user is not None:
                            user_label = pattroler.cfg.get('user_label')
                            user_display = get_user_display_name(claim_user, user_label)
                            user_details = format_user_details(claim_user, user_label)

                            with st.popover(f"❌ OCCUPIED: {user_display}"):
                                st.markdown(user_details)
                        else:
                            state, _ = gpu_state(gpu_info)
                            st.write({'FREE': '✔️ FREE', 'UNKNOWN': 'Reservation state unknown'}[state])
                    bookings = [b for b in (active, gpu_info.get('next_reservation')) if b]
                    if bookings:
                        if active:
                            owner_email = active.get('owner_email', '')
                            owner = next((u for u in pattroler.cfg.get('reservation_users', [])
                                          if identity_email(owner_email) and identity_email(u.get('email')) == identity_email(owner_email)),
                                         {'email': owner_email})
                            owner_display = (owner_label(active) if active.get('owner_type') == 'name'
                                             else active.get('owner_name') or get_user_display_name(owner))
                            label = f'🔒 RESERVED: {owner_display}'
                        else:
                            label = f"🔓 Reservations in {reservation_countdown(gpu_info['next_reservation'])}"
                        with st.popover(label, help='View active reservation details' if active else 'View upcoming reservations'):
                            zone = pattroler.cfg.get('timezone', 'Europe/Ljubljana')
                            for booking in bookings:
                                if booking.get('owner_name'):
                                    st.text(booking['owner_name'])
                                st.write(owner_label(booking))
                                start = parse_time(booking['start_at'])
                                duration_hours = (parse_time(booking['end_at']) - start).total_seconds() / 3600
                                st.write(f"Start: {start.astimezone(ZoneInfo(zone)):%Y-%m-%d %H:%M} ({zone})")
                                st.write(f"Duration: {duration_hours:g} {'hour' if duration_hours == 1 else 'hours'}")
                                if booking.get('note'):
                                    st.write(booking['note'])
                    if not active:
                        st.caption("last change %s ago" % claim_age)
                    if show_json:
                        st.json({k: v for k, v in gpu_info.items() if k not in ('active_reservation', 'next_reservation')})

                    total += 1
                    total_available += int(gpu_state(gpu_info)[1])
                    with total_info:
                        st.caption("Total available: %d / %d" % (total_available, total))
