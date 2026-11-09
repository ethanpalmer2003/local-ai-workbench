@echo off
rem Thin wrapper - all logic lives in the Python module.
rem Any override goes through %* below - no need to edit this file.
rem Examples:
rem   launch_llamacpp_pi_agent.bat --ini-profile swift15
rem   launch_llamacpp_pi_agent.bat --ini-set ctx-size=32768
rem   launch_llamacpp_pi_agent.bat --ini-skip --ini-set ctx-size=8192
rem - Default agent is Pi; choose others with --client little-coder|ohmypi|nanocoder|none.

set "RUN_TITLE=Pi"
set "RUN_MODULE=scripts.launchers.llamacpp.llamacpp_pi"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
