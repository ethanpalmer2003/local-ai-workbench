@echo off
rem Last-run evidence table for the long opt-in checks; add --check to fail on stale rows.

set "RUN_TITLE=Capability Matrix"
set "RUN_MODULE=scripts.tools.capability_matrix"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
