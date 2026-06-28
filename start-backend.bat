@echo off
chcp 65001 >nul
title 砚迟后端

echo 启动砚迟后端（pm2 守护）...
pm2 resurrect 2>nul || pm2 start backend/main.py --interpreter "C:\Python312\python.exe" --name yanchi
echo 后端已启动
pause
