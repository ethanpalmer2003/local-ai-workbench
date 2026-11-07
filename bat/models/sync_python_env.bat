@echo off
setlocal
pushd "C:\AI"
title Sync Python Environment
rem - uv must manage scripts\.venv; without this it creates .\.venv instead
set "UV_PROJECT_ENVIRONMENT=C:\AI\scripts\.venv"
uv sync --frozen --group dev %*
set "SYNC_EXIT=%ERRORLEVEL%"
popd
if not "%SYNC_EXIT%"=="0" (
    echo [FAIL] uv sync exited %SYNC_EXIT%
) else (
    echo [OK] scripts\.venv matches uv.lock
)
pause
exit /b %SYNC_EXIT%
