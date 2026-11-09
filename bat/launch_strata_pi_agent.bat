@echo off
set "RUN_TITLE=Strata Pi"
set "RUN_MODULE=scripts.launchers.strata.strata_pi"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
