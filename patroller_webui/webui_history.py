import sys
import streamlit as st
import pandas as pd
import numpy as np 
import time

from patroller_webui import PatrollerHistory, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH

def run_history_heatmap():

    with st.spinner('Retrieving server gpus and history'):
        pattroler_history = PatrollerHistory(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH,
                                             sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH)
        
        df = pattroler_history.get_history()
        df.index = pd.to_datetime(df.index, unit='s')

    with st.form('hist-heatmap-filtering-form'):        
        selected_servers = st.multiselect("Servers", pattroler_history.list_servers(), pattroler_history.list_servers())

        per_day_index = df.index.to_period('D')

        selected_date = st.date_input(
            "Select day",
            per_day_index.max().to_timestamp().to_pydatetime(),
            min_value=per_day_index.min().to_timestamp().to_pydatetime(),
            max_value=per_day_index.max().to_timestamp().to_pydatetime(),
            format="DD.MM.YYYY",
        )

        st.form_submit_button('Apply filter')

    with st.spinner('Converting to history heatmap'):
        
        # retrieve selected server GPUs
        server_gpus, _ = pattroler_history.find_server_gpus(selected_servers)

        # get global indexes for all selected 
        server_gpus_ids = {n:dict() for n,_ in server_gpus.items()}
        index = 0
        for n,gpus in server_gpus.items():
            for g in gpus:
                server_gpus_ids[n][g] = index
                index += 1
        
        df_on_day = df[per_day_index == pd.to_datetime(selected_date).to_period('D')]
        times_on_day = df_on_day.index.unique().to_list()

        # convert to occupancy blocks
        num_gpus = sum([len(g) for n,g in server_gpus.items() ])
        occupancy_blocks = np.zeros((len(times_on_day), num_gpus), dtype=np.uint8)

        for i,timestamp in enumerate(times_on_day):
            for row in df_on_day.loc[df_on_day.index == timestamp].itertuples():
                server, gpu, user, age = row.server, row.gpu, row.user, row.age
                if server in selected_servers:
                    j = server_gpus_ids[server][gpu]
                    occupancy_blocks[i,j] = 1

        def color_true_red(val):
            color = 'red' if val == True else 'green'
            return f'background-color: {color}'

        df_block = pd.DataFrame(occupancy_blocks, index=times_on_day)
        df_block.columns = [f'{n}-{i}' for n,g in server_gpus_ids.items() for i,_ in enumerate(g)]
        df_block = df_block.sort_index(ascending=False)

        st.dataframe(df_block.style.applymap(color_true_red), selection_mode=[])

def run_history_dashboard():  

    pattroler_history = PatrollerHistory(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH,
                                         sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH)

    # retrieve all server GPUs    
    server_gpus, server_offline = pattroler_history.find_server_gpus()
    
    df = pattroler_history.get_history()
    df.index = pd.to_datetime(df.index, unit='s')

    times = df.index.unique().to_list()
    per_day_index = df.index.to_period('D')

    selected_date = st.date_input(
        "Select day",
        per_day_index.max().to_timestamp().to_pydatetime(),
        min_value=per_day_index.min().to_timestamp().to_pydatetime(),
        max_value=per_day_index.max().to_timestamp().to_pydatetime(),
        format="DD.MM.YYYY",
    )

    df_on_day = df[per_day_index == pd.to_datetime(selected_date).to_period('D')]

    selected_timestamp = st.select_slider("Select time of day", options=df_on_day.index.unique().to_list()[::-1])

    selected_df = df[df.index == selected_timestamp]

    num_gpus = sum([len(g) for n,g in server_gpus.items() ])
    num_gpus_occupided = len(selected_df)

    st.caption("Total available: %d / %d" % (num_gpus - num_gpus_occupided, num_gpus))
    for server_name,gpu_ids in server_gpus.items():
        
        if server_name in server_offline:
            server_display_name = f"{server_name} - offline (may not have complete list of gpus)"
        else:
            server_display_name = server_name 

        with st.expander(server_display_name,expanded=True):
            cols_title = st.columns(len(gpu_ids))
            cols_info = st.columns(len(gpu_ids))
            gpu_index = 0
            for gpu_index,gpu_id in enumerate(gpu_ids):
                with cols_title[gpu_index]:
                    st.write("GPU %s %d" % (server_name,gpu_index))
                
                with cols_info[gpu_index]:
                    if gpu_id in selected_df['gpu'].to_list():
                        user = selected_df[selected_df['gpu'] == gpu_id]['user'][0]
                        st.write("❌ OCCUPIED: {0}".format(user), unsafe_allow_html=True)
                        
                        
                        claim_age = selected_df[selected_df['gpu'] == gpu_id]['age'][0]
                        claim_age_str = time.strftime('%Mm %Ssec', time.gmtime(claim_age))                    
                        if claim_age > 60*60:
                            claim_age_str = '%dh %s' % (int(claim_age/(60*60)), claim_age_str)
                        st.caption("since %s" % claim_age_str)
                    else:
                        st.write("✔️ FREE " )


