@echo off
set "RUN_TITLE=Strata Desktop"
set "RUN_MODULE=scripts.launchers.strata.ui"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
