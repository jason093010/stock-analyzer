#!/bin/bash
# 1. 在背景啟動 AI 分析程式
python background_worker.py &

# 2. 啟動 Streamlit 網頁主程式
streamlit run app.py --server.port $PORT --server.address 0.0.0.0