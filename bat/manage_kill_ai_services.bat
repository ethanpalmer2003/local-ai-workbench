@echo off
setlocal
pushd "C:\AI"
title Stop C AI Services
rem --non-agents keeps coding agents, llama.cpp and Strata running.
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.kill_all_services %*
set "KILL_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %KILL_EXIT%
