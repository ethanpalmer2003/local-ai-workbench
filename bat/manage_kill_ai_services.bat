@echo off
rem --non-agents keeps coding agents, llama.cpp and Strata running.

set "RUN_TITLE=Stop C AI Services"
set "RUN_MODULE=scripts.launchers.kill_all_services"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
