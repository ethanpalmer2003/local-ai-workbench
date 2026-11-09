@echo off
rem - Prunes orphaned temp extractions, aborted downloads and old logs. --dry-run to preview.

set "RUN_TITLE=Cleanup State"
set "RUN_MODULE=scripts.tools.state_cleanup"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
