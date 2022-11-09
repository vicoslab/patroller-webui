import sys, os

import streamlit as st
import json
import urllib.request, base64

import time

__DEFAULT_CONFIG_PATH = "/etc/patroller/web-ui.json"

def load_config():
    cfg_path = sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH

    if os.path.exists(cfg_path):
        with open(cfg_path,'r') as f:
            cfg = json.load(f)
    else:
        cfg = dict(servers=[])
    
    return cfg

def run():
    cfg = load_config()

    
    gpu_servers = cfg['servers']
    if len(gpu_servers) <= 0:
        st.error("No servers found in config or missing config file (should be provided as cmd or in '%s')" % __DEFAULT_CONFIG_PATH)
        return
        
    url_auth = None
    if 'http_auth_user' in cfg and 'http_auth_pass' in cfg:
        url_auth = base64.b64encode(('%s:%s' % (cfg['http_auth_user'],
                                                cfg['http_auth_pass'])).encode('ascii'))

    st.set_page_config(layout="wide")

    show_men_use = st.sidebar.checkbox("Show GPU memory utilization", value=True)
    show_cpu_use = st.sidebar.checkbox("Show GPU processor utilization",value=False)
    show_temp = st.sidebar.checkbox("Show GPU temperature",value=False)
    show_json = st.sidebar.checkbox("Show raw info",value=False)
    show_gpu_id = st.sidebar.checkbox("Show GPU ID instead of index",value=False)

    total_info = st.empty()
    st.button("Refresh")

    num_metrics = ((show_cpu_use or show_men_use) + show_temp)

    total = 0
    total_available = 0
    for server_cfg in gpu_servers:
        server_name = server_cfg['name']
        server_url = server_cfg['url']
        
        try:
            request = urllib.request.Request(server_url)
            
            if 'http_auth_user' in server_cfg and 'http_auth_pass' in server_cfg:
                url_auth = base64.b64encode(('%s:%s' % (server_cfg['http_auth_user'],
                                                         server_cfg['http_auth_pass'])).encode('ascii'))

            if url_auth is not None and not server_cfg.get('disable_auth'):
                request.add_header("Authorization", "Basic %s" % url_auth.decode("ascii"))

            with urllib.request.urlopen(request, timeout=5) as url:
                gpu_data = json.loads(url.read().decode())
        
        except Exception as ex:
            import traceback
            print("Unable to retrieve status from '%s'" % server_url)
            traceback.print_exception(type(ex), ex, ex.__traceback__)
            
            with st.expander(server_name,expanded=True):
                st.error("Unable to retrieve status from '%s'" % server_url)
                
            continue

        with st.expander(server_name,expanded=True):
            cols_title = st.columns(len(gpu_data))
            cols_metrics = st.columns(len(gpu_data)* num_metrics)
            cols_info = st.columns(len(gpu_data))
            gpu_index = 0
            for gpu_index,(gpu_id,gpu_info) in enumerate(gpu_data.items()):
                with cols_title[gpu_index]:
                    if show_gpu_id:
                        st.write(gpu_id)
                    else:
                        st.write("GPU %s %d" % (server_name,gpu_index))
                metric_idx = 0
                if show_men_use or show_cpu_use:
                    with cols_metrics[gpu_index * num_metrics + metric_idx]:
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
                    with cols_metrics[gpu_index * num_metrics + metric_idx]:
                        st.metric("Temperature", '%d °C' % gpu_info['gtemp'])
                        metric_idx += 1

                with cols_info[gpu_index]:
                    claim_age = time.strftime('%Mm %Ssec', time.gmtime(gpu_info['claim']['age']))
                    
                    if gpu_info['claim']['age'] > 60*60:
                        claim_age = '%dh %s' % (int(gpu_info['claim']['age']/(60*60)), claim_age)
                        
                    if "user" in gpu_info['claim']:
                        st.write("❌ OCCUPIED: <a href=\"mailto:{0}\">{0}</a>".format(gpu_info['claim']['user']),
                                 unsafe_allow_html=True)
                    else:
                        st.write("✔️ FREE " )
                    st.caption("last change %s ago" % claim_age)
                    if show_json:
                        st.json(gpu_info)

                    total += 1
                    total_available += 0 if "user" in gpu_info['claim'] else 1
                    with total_info:
                        st.caption("Total available: %d / %d" % (total_available, total))
