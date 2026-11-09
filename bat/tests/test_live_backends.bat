@echo off
rem Native backend probes: each engine/model loads and answers. No launcher/proxy wiring.
rem `--only NAME...` narrows the probe list. Refuses if a user session holds a service port.

set "RUN_TITLE=Live Backends"
set "RUN_MODULE=scripts.tests.run"
call "%~dp0..\_run.bat" --suite backends %*
exit /b %ERRORLEVEL%
