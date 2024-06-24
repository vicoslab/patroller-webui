import sys
import streamlit as st
import pandas as pd
import numpy as np 

from patroller_webui import Patroller, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH

def run_statistics():
    with st.spinner('Retrieving server gpus and history'):

        pattroler = Patroller(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH)
        # retrieve all server GPUs
        server_gpus = {server_cfg['name']: [gpu_id for gpu_id,_ in server_cfg['data'].items()] for server_cfg in pattroler}
    
        server_gpus_ids = {n:dict() for n,_ in server_gpus.items()}

        index = 0
        for n,gpus in server_gpus.items():
            for g in gpus:
                server_gpus_ids[n][g] = index
                index += 1

        # load history data
        df = pd.read_parquet(__DEFAULT_DATABASE_PATH)   
        df.index = pd.to_datetime(df.index, unit='s')

    # add timestamp_gpu so that we can count unique instance per each (timestamp,gpu) instance
    df['timestamp_gpu'] = list(zip(df.index, df['gpu']))

    # prepare indexes for grouping
    per_year_index = df.index.to_period('Y')
    per_year_index.name = 'year'

    per_month_index = df.index.to_period('M')
    per_month_index.name = 'month'
    
    per_day_index = df.index.to_period('D')
    per_day_index.name = 'day'

    per_hour_index = df.index.to_period('h')
    per_hour_index.name = 'hour'

    df = df.set_index(per_year_index, append=True)
    df = df.set_index(per_month_index, append=True)
    df = df.set_index(per_day_index, append=True)
    df = df.set_index(per_hour_index, append=True)

    freq_val = ['year', 'month', 'day', 'hour']    
    freq_factor = [365*24*60, 30.5*24*60, 24*60, 60]

    freq_disp = st.multiselect('Select group frequency', freq_val, ['month'])
    
    tab_table, tab_graph = st.tabs(['Table', 'Graph'])

    for freq in freq_disp:
        factor = freq_factor[freq_val.index(freq)]
        # count per-gpu it usage by year/month/day/hour
        df_per_freq = df.reset_index().groupby([freq,'server'])
        
        # count unique entries of timestamp (to see how many times it was used - it could have multiple entries for same timestamp !!)
        df_per_freq = df_per_freq['timestamp_gpu'].nunique()

        # then unstack
        df_per_freq = df_per_freq.unstack('server', fill_value=0).reindex(columns=server_gpus.keys(), fill_value=0)

        # convert to utilization
        df_per_freq_util = df_per_freq.copy()
        for n,gpus in server_gpus.items():
            df_per_freq_util[n] = (df_per_freq_util[n]/factor) / len(gpus)
    
        with tab_table:
            st.header('Per ' + freq)

            col1,col2 = st.columns(2)
            with col1:
                st.caption("GPU-hours: ")
                st.dataframe(df_per_freq/60)
            
            with col2:
                st.caption("Utilization of the server (1.0 is 100% of the server): ")
                st.dataframe(df_per_freq_util)
    
        with tab_graph:
            st.header('Per ' + freq)
            
            df_per_freq.index = df_per_freq.index.to_timestamp()
            df_per_freq_util.index = df_per_freq_util.index.to_timestamp()

            col1,col2 = st.columns(2)
            with col1:
                st.caption("GPU-hours: ")
                #fig = px.bar(df_per_freq/60)
                #st.plotly_chart(fig, use_container_width=True)                
                st.bar_chart(df_per_freq/60)

            with col2:
                
                st.caption("Utilization of the servers (1.0 is 100% of one server): ")
                
                #fig = px.line(df_per_freq_util)
                #fig.update_traces(mode="markers+lines")
                #st.plotly_chart(fig, use_container_width=True)     
                st.bar_chart(df_per_freq_util)           



