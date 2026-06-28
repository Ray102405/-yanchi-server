@echo off
chcp 65001 >nul
title 砚迟 · FastAPI 后端（pm2 守护）

echo ╔══════════════════════════════════════════╗
echo ║  砚迟 · Python FastAPI 后端（pm2 守护）   ║
echo ║  自动重启 · 开机自启                      ║
echo ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: pm2 恢复/启动
pm2 resurrect 2>nul || pm2 start backend\main.py --interpreter "C:\Python312\python.exe" --name yanchi

echo.
echo ────────────────────────────────────────────
echo   🧠 砚迟已上线（pm2 守护中）
echo   💡 挂了自动重启，不用管了
echo   📋 pm2 status  查看状态
echo   📋 pm2 logs yanchi  查看日志
echo ────────────────────────────────────────────
echo.

:: 打开前端
start "" "http://localhost:3000"

echo 按任意键关闭此窗口（后端仍在后台运行）...
pause >nul
echo.
echo 后端仍在 pm2 中运行，关闭窗口不影响。
timeout /t 3 /nobreak >nul
