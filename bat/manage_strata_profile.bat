@echo off
set "RUN_TITLE=Strata Profile Links"
set "RUN_MODULE=scripts.tools.strata_profile"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
