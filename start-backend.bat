@echo off
chcp 65001 >nul
title 砚迟后端

set YANCHI_HOST=0.0.0.0
set YANCHI_PORT=2612

"C:\Python312\python.exe" "C:\Users\Ray\yanchi-server\backend\main.py"
