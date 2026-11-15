@echo off
set "RUN_TITLE=Low Integrity Labels"
set "RUN_MODULE=scripts.tools.low_integrity"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
