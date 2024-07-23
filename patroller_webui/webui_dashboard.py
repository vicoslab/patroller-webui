import sys, time

import streamlit as st

from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH

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
                st.error("Unable to retrieve status from '%s'" % server_url)              
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
                    claim_age = time.strftime('%Mm %Ssec', time.gmtime(gpu_info['claim']['age']))
                    
                    if gpu_info['claim']['age'] > 60*60:
                        claim_age = '%dh %s' % (int(gpu_info['claim']['age']/(60*60)), claim_age)
                        
                    if "user" in gpu_info['claim'] and gpu_info['claim']['user'] is not None:
                        
                        if type(gpu_info['claim']['user']) is dict:
                            user_display = str(gpu_info['claim']['user'][pattroler.cfg['user_label']])                            
                            user_details = ""
                            for k,v in gpu_info['claim']['user'].items():
                                user_details += f"\n  * **{k}:** {v}"
                        else:
                            user_display = gpu_info['claim']['user']
                            user_details = gpu_info['claim']['user']
                        
                        with st.popover(f"❌ OCCUPIED: {user_display}"):
                            st.markdown(user_details)


                    else:
                        st.write("✔️ FREE " )
                    st.caption("last change %s ago" % claim_age)
                    if show_json:
                        st.json(gpu_info)

                    total += 1
                    total_available += 0 if "user" in gpu_info['claim'] and gpu_info['claim']['user'] is not None else 1
                    with total_info:
                        st.caption("Total available: %d / %d" % (total_available, total))
