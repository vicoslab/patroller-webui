"""Bootstrap deep links before Streamlit 1.36 first discovers st.navigation.

The first browser can request /reservations while Streamlit still uses legacy
pages discovery. Delegate to the normal entrypoint, including URL-token capture;
st.navigation owns all subsequent routing. Never implement a second page here.
"""
from patroller_webui.webui import run

run()
