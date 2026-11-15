@echo off
rem Native launcher/proxy wiring: starts the real launchers, generates output, stops owned processes.
rem Refuses if a user session already holds a service port.

set "RUN_TITLE=Live Launchers"
set "RUN_MODULE=scripts.tests.run"
call "%~dp0..\_run.bat" --suite launchers %*
exit /b %ERRORLEVEL%
