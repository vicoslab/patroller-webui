#!/bin/bash

# start chronicle in background
python -e chronicle.py & 
chronicle_pid=$!

# then start webui using streamlit
streamlit run /code/patroller_webui/webui.py

# stop chronicle when finished
kill -9 $chronicle