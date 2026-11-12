@echo off
setlocal
pushd "C:\AI"
title Sync Python Environment
uv sync --frozen --group dev %*
set "SYNC_EXIT=%ERRORLEVEL%"
popd
if not "%SYNC_EXIT%"=="0" (
    echo [FAIL] uv sync exited %SYNC_EXIT%
) else (
    echo [OK] .venv matches uv.lock
)
pause
exit /b %SYNC_EXIT%
