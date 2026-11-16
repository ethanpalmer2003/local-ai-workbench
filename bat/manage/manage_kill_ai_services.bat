@echo off
rem --non-agents keeps coding agents, llama.cpp and Strata running.

set "RUN_TITLE=Stop C AI Services"
set "RUN_MODULE=scripts.launchers.kill_all_services"
rem --yes because the double-click is the confirmation; pass --non-agents to spare the agent stack.
call "%~dp0..\_run.bat" --yes %*
exit /b %ERRORLEVEL%
