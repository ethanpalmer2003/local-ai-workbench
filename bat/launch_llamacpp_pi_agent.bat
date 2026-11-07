@echo off
setlocal
rem Thin wrapper - all logic lives in the Python module.
rem Any override goes through %* below - no need to edit this file.
rem Examples:
rem   launch_llamacpp_pi_agent.bat --ini-profile swift15
rem   launch_llamacpp_pi_agent.bat --ini-set ctx-size=32768
rem   launch_llamacpp_pi_agent.bat --ini-skip --ini-set ctx-size=8192
rem - Default agent is Pi; choose others with --client little-coder|ohmypi|nanocoder|none.

set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"
title Pi
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.llamacpp.llamacpp_pi %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %LAUNCH_EXIT%
