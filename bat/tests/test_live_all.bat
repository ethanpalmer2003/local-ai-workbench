@echo off
rem Both native suites: launcher/proxy wiring, then every backend probe.
rem Refuses if a user session already holds a service port.

set "RUN_TITLE=Live All"
set "RUN_MODULE=scripts.tests.run"
call "%~dp0..\_run.bat" --suite all %*
exit /b %ERRORLEVEL%
