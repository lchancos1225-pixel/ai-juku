@echo off
chcp 65001 >nul
REM AI-Juku Server Auto-Restart Script for Windows VPS
REM Port 8000 を自動検知・解放してからサーバーを起動

echo ========================================
echo AI-Juku Server Restart
echo ========================================
echo.

REM Python プロセスの確認と終了
echo [1/3] Checking for existing Python processes on port 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000') do (
    echo    Found process PID: %%a
    taskkill /F /PID %%a 2>nul
    echo    Killed process %%a
)

REM 少し待機
timeout /t 2 /nobreak >nul

echo.
echo [2/3] Starting AI-Juku server...
echo    Server will be available at: http://127.0.0.1:8000
echo    Press Ctrl+C to stop
echo.

REM サーバー起動
cd C:\Users\Administrator\ai-juku
.venv\Scripts\uvicorn.exe ai_school.app.main:app --host 127.0.0.1 --port 8000 --reload

echo.
echo ========================================
echo Server stopped
echo ========================================
pause
