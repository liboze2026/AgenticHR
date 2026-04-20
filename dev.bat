@echo off
title AgenticHR Dev

set ROOT=%~dp0

start "Backend :8000" cmd /k "cd /d %ROOT% && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

start "Frontend :3000" cmd /k "cd /d %ROOT%frontend && npm run dev"

timeout /t 4 /nobreak >nul
start http://localhost:3000

echo Backend : http://localhost:8000
echo Frontend: http://localhost:3000
echo API docs: http://localhost:8000/docs
