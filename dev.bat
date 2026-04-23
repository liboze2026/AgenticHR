@echo off
chcp 65001 >nul
setlocal EnableExtensions
title AgenticHR Dev Launcher

set "ROOT=%~dp0"
set "BACKEND_PORT=8000"
set "FRONTEND_PORT=3000"
set "PY=%ROOT%.venv/Scripts/python.exe"
set "ALEMBIC=%ROOT%.venv/Scripts/alembic.exe"

echo ============================================================
echo   AgenticHR Dev Launcher
echo ============================================================

if not exist "%PY%" (
    echo [ERROR] Python venv not found: %PY%
    goto hold
)
if not exist "%ROOT%frontend/node_modules" (
    echo [WARN] frontend/node_modules missing, running npm install ...
    pushd "%ROOT%frontend"
    call npm install
    popd
)

echo [1/4] Cleaning ports %BACKEND_PORT% and %FRONTEND_PORT% ...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%BACKEND_PORT% " ^| findstr "LISTENING"') do (
    echo        kill backend PID %%a
    taskkill /F /PID %%a >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%FRONTEND_PORT% " ^| findstr "LISTENING"') do (
    echo        kill frontend PID %%a
    taskkill /F /PID %%a >nul 2>&1
)

echo [2/4] Running alembic upgrade head ...
pushd "%ROOT%"
"%ALEMBIC%" upgrade head
if errorlevel 1 (
    echo [ERROR] Alembic migration failed.
    popd
    goto hold
)
popd

echo [3/4] Starting Backend on http://localhost:%BACKEND_PORT% ...
start "AgenticHR Backend :%BACKEND_PORT%" cmd /k ""%PY%" -m uvicorn app.main:app --reload --port %BACKEND_PORT% --host 0.0.0.0"

echo [4/4] Starting Frontend on http://localhost:%FRONTEND_PORT% ...
start "AgenticHR Frontend :%FRONTEND_PORT%" cmd /k "cd /d "%ROOT%frontend" && npm run dev"

echo Waiting for Backend (%BACKEND_PORT%) ...
set /a btries=0
:wait_backend
set /a btries+=1
if %btries% GTR 60 (
    echo [WARN] Backend not ready after 60s, opening browser anyway.
    goto wait_frontend
)
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 goto wait_backend
echo        Backend port LISTENING (after %btries%s)

echo Probing Backend health ...
set /a htries=0
:wait_health
set /a htries+=1
if %htries% GTR 30 (
    echo [WARN] Backend health probe timeout, opening browser anyway.
    goto wait_frontend
)
timeout /t 1 /nobreak >nul
"%PY%" -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%BACKEND_PORT%/openapi.json',timeout=2).status==200 else 1)" >nul 2>&1
if errorlevel 1 goto wait_health
echo        Backend healthy (after %htries%s)

:wait_frontend
echo Waiting for Frontend (%FRONTEND_PORT%) ...
set /a ftries=0
:wait_frontend_loop
set /a ftries+=1
if %ftries% GTR 30 (
    echo [WARN] Frontend not ready after 30s, opening browser anyway.
    goto open_browser
)
timeout /t 1 /nobreak >nul
netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul 2>&1
if errorlevel 1 goto wait_frontend_loop
echo        Frontend port LISTENING (after %ftries%s)

:open_browser
start "" http://localhost:%FRONTEND_PORT%

echo.
echo ============================================================
echo   Backend  : http://localhost:%BACKEND_PORT%
echo   Frontend : http://localhost:%FRONTEND_PORT%
echo   API docs : http://localhost:%BACKEND_PORT%/docs
echo ============================================================
echo   Close the Backend and Frontend windows to stop services.
echo   This launcher will close in 5 seconds ...
timeout /t 5 /nobreak >nul
exit /b 0

:hold
echo.
pause
exit /b 1