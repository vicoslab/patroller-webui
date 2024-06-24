import sys
import streamlit as st
import pandas as pd
import numpy as np 
import time
from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH

def run_history_heatmap():

    pattroler = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)
    
    with st.form('filtering-form'):
        server_names = [s['name'] for s in pattroler.cfg['servers']]
        selected_servers = st.multiselect("Servers", server_names, server_names)

        st.form_submit_button('Apply filter')

    with st.spinner('Retrieving server gpus and history'):
        # retrieve all server GPUs
        server_gpus = {server_cfg['name']: [gpu_id for gpu_id,_ in server_cfg['data'].items()] for server_cfg in pattroler if server_cfg['name'] in selected_servers}

        server_gpus_ids = {n:dict() for n,_ in server_gpus.items()}
        
        index = 0
        for n,gpus in server_gpus.items():
            for g in gpus:
                server_gpus_ids[n][g] = index
                index += 1
        
        # load history data
        df = pd.read_parquet(sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH)   
        df.index = pd.to_datetime(df.index, unit='s')

        times = df.index.unique().to_list()

        # convert to occupancy blocks
        num_gpus = sum([len(g) for n,g in server_gpus.items() ])
        occupancy_blocks = np.zeros((len(times), num_gpus), dtype=np.uint8)

        for i,timestamp in enumerate(times):
            for row in df.loc[df.index == timestamp].itertuples():
                server, gpu, user, age = row.server, row.gpu, row.user, row.age
                if server in selected_servers:
                    j = server_gpus_ids[server][gpu]
                    occupancy_blocks[i,j] = 1

        def color_true_red(val):
            color = 'red' if val == True else 'green'
            return f'background-color: {color}'

        df_block = pd.DataFrame(occupancy_blocks, index=times)
        df_block.columns = [f'{n}-{i}' for n,g in server_gpus_ids.items() for i,_ in enumerate(g)]
        df_block = df_block.sort_index(ascending=False)

        st.dataframe(df_block.style.applymap(color_true_red), selection_mode=[])

def run_history_dashboard():  

    pattroler = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)

    # retrieve all server GPUs
    server_gpus = {server_cfg['name']: [gpu_id for gpu_id,_ in server_cfg['data'].items()] for server_cfg in pattroler}
    
    # load history data
    df = pd.read_parquet(sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH)   
    df.index = pd.to_datetime(df.index, unit='s')

    times = df.index.unique().to_list()

    selected_datetime = st.select_slider("Selected date", options=times[::-1])
    selected_df = df[df.index == selected_datetime]

    num_gpus = sum([len(g) for n,g in server_gpus.items() ])
    num_gpus_occupided = len(selected_df)

    st.caption("Total available: %d / %d" % (num_gpus - num_gpus_occupided, num_gpus))
    for server_name,gpu_ids in server_gpus.items():

        with st.expander(server_name,expanded=True):
            cols_title = st.columns(len(gpu_ids))
            cols_info = st.columns(len(gpu_ids))
            gpu_index = 0
            for gpu_index,gpu_id in enumerate(gpu_ids):
                with cols_title[gpu_index]:
                    st.write("GPU %s %d" % (server_name,gpu_index))
                
                with cols_info[gpu_index]:
                    if gpu_id in selected_df['gpu'].to_list():
                        user = selected_df[selected_df['gpu'] == gpu_id]['user'][0]
                        st.write("❌ OCCUPIED: <a href=\"mailto:{0}\">{0}</a>".format(user),
                                 unsafe_allow_html=True)
                        
                        
                        claim_age = selected_df[selected_df['gpu'] == gpu_id]['age'][0]
                        claim_age_str = time.strftime('%Mm %Ssec', time.gmtime(claim_age))                    
                        if claim_age > 60*60:
                            claim_age_str = '%dh %s' % (int(claim_age/(60*60)), claim_age_str)
                        st.caption("since %s" % claim_age_str)
                    else:
                        st.write("✔️ FREE " )


