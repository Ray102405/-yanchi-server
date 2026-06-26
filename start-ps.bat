@echo off
chcp 65001 >nul
title 砚迟 · FastAPI 后端

:: 端口设置（改这里即可，需与 index.html 中的 YANCHI_PORT 保持一致）
set YANCHI_PORT=2612
set YANCHI_HOST=0.0.0.0

echo ╔══════════════════════════════════════════╗
echo ║  砚迟 · Python FastAPI 后端              ║
echo ║  复用 Claude Code API 配置               ║
echo ║  支持流式输出 + 思考链                    ║
echo ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

:: 关掉旧的 Python 后端
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue" 2>nul

:: 启动后端
start /B python backend\main.py

:: 等后端就绪
timeout /t 5 /nobreak >nul

echo.
echo ────────────────────────────────────────────
echo   🧠 砚迟已上线 → http://localhost:%YANCHI_PORT%
echo   💡 流式输出 + 思考链已启用
echo   ⏹  关闭此窗口即可停止服务
echo ────────────────────────────────────────────
echo.

:: 打开前端
start "" "http://localhost:%YANCHI_PORT%"

echo 按任意键关闭服务...
pause >nul

:: 关闭 Python 进程
powershell -Command "Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue"
