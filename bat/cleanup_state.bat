@echo off
setlocal
pushd "C:\AI"
title Cleanup State
rem - Prunes orphaned temp extractions, aborted downloads and old logs. --dry-run to preview.
"scripts\.venv\Scripts\python.exe" -m scripts.tools.state_cleanup %*
set "CLEAN_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %CLEAN_EXIT%
