#!/bin/bash

export DIR="$(dirname "$0")"

# start chronicle in background
python3 ${DIR}/patroller_webui/chronicle.py & 
chronicle_pid=$!

# then start webui using streamlit
streamlit run ${DIR}/patroller_webui/webui.py

# stop chronicle when finished
kill -9 $chronicle_pid