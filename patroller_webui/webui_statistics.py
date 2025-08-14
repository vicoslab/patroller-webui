import sys
import streamlit as st
import pandas as pd
import numpy as np 

from patroller_webui import PatrollerHistory, __DEFAULT_CONFIG_PATH, __DEFAULT_DATABASE_PATH

def run_statistics():
    with st.spinner('Retrieving server gpus and history'):

        pattroler_history = PatrollerHistory(sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH,
                                             sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH)

        # retrieve all server GPUs    
        server_gpus, _ = pattroler_history.find_server_gpus()

        df = pattroler_history.get_history()
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

        per_minute_index = df.index.to_period('min')
        per_minute_index.name = 'minute'

        df = df.set_index(per_year_index, append=True)
        df = df.set_index(per_month_index, append=True)
        df = df.set_index(per_day_index, append=True)
        df = df.set_index(per_hour_index, append=True)
        df = df.set_index(per_minute_index, append=True)

    freq_val = ['year', 'month', 'day', 'hour', 'minute']    
    freq_factor = [365*24*60, 30.5*24*60, 24*60, 60, 1]

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


def format_since(delta_days):
    """Format days as 'DDD days' and append human-readable breakdown if > 30 days."""
    delta_days = int(round(delta_days))
    base_str = f"{delta_days:03d} days"
    
    if delta_days <= 30:
        return base_str
    
    years = delta_days // 365
    months = (delta_days % 365) // 30
    days = delta_days - years * 365 - months * 30

    parts = []
    if years > 0:
        parts.append(f"{years} year{'s' if years != 1 else ''}")
    if months > 0:
        parts.append(f"{months} month{'s' if months != 1 else ''}")
    if days > 0:
        parts.append(f"{days} day{'s' if days != 1 else ''}")

    return f"{base_str} ({', '.join(parts)})"

def run_user_statistics():
    with st.spinner('Loading total GPU usage history by user...'):
        pattroler_history = PatrollerHistory(
            sys.argv[1] if len(sys.argv) > 1 else __DEFAULT_CONFIG_PATH,
            sys.argv[2] if len(sys.argv) > 2 else __DEFAULT_DATABASE_PATH
        )

        server_gpus, _ = pattroler_history.find_server_gpus()
        total_gpus = sum(len(gpus) for gpus in server_gpus.values())

        df = pattroler_history.get_history()
        df.index = pd.to_datetime(df.index, unit='s')
        df['timestamp_gpu'] = list(zip(df.index, df['gpu']))

    usage_counts = df.groupby('user')['timestamp_gpu'].nunique()
    gpu_hours = usage_counts / 60

    # Compute utilization relative to total GPU-minutes possible
    total_minutes = gpu_hours.sum() * 60  # sum of all minutes across users
    utilization_percent = (usage_counts / (total_minutes if total_minutes > 0 else 1)) * 100

    # Find latest usage timestamp for each user
    latest_usage = df.groupby('user').apply(lambda g: g.index.max())

    # Make sure all timestamps are tz-naive
    latest_usage = latest_usage.dt.tz_localize(None)

    # Use timezone-naive "now"
    now = pd.Timestamp.utcnow().tz_localize(None)

    # Calculate days since last use and format
    days_since = (now - latest_usage).dt.total_seconds() / (24 * 3600)
    since_str = days_since.apply(format_since)

    # Build results table
    results_df = pd.DataFrame({
        'GPU-Hours': gpu_hours.round(2),
        'Usage (%)': utilization_percent.sort_values(ascending=False).round(2),
        #'Last Used': latest_usage.dt.strftime('%Y-%m-%d %H:%M:%S'),
        'Days Since Used': since_str
    }).sort_values('GPU-Hours', ascending=False)

    st.header("Total GPU Usage by User")
    st.dataframe(results_df, use_container_width=True)

    st.header("GPU-Hours per User (Bar Chart)")
    st.bar_chart(gpu_hours.sort_values(ascending=False))

