import streamlit as st

from webui_dashboard import run_dashboard
from webui_reservations import run_reservations
from webui_history import run_history_dashboard, run_history_heatmap
from webui_statistics import run_statistics, run_user_statistics
from patroller_webui.write_access import capture_url_token

def run():
    st.set_page_config(layout="wide", page_title="Patroller")
    capture_url_token()

    dashboard = st.Page(run_dashboard, title="Dashboard", url_path="dashboard", icon=":material/shelf_position:", default=True)
    history_dashboard = st.Page(run_history_dashboard, title="History Dashboard", url_path="history_dashboard", icon=":material/history:")
    history_heatmap = st.Page(run_history_heatmap, title="History Heatmap", url_path="history_heatmap", icon=":material/history:")

    statistics = st.Page(run_statistics, title="Statistics", url_path="statistics", icon=":material/pie_chart:")
    statistcis_user = st.Page(run_user_statistics, title="User Statistics", url_path="statistics_user", icon=":material/pie_chart:")

    reservations = st.Page(run_reservations, title="Reservations", url_path="reservations", icon=":material/lock:")

    pg = st.navigation(
        [dashboard, reservations, history_dashboard, history_heatmap, statistics, statistcis_user]
    )

    pg.run()

if __name__ == "__main__":
    run()