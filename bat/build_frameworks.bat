@echo off
rem - Default: one new terminal per source build. --foreground builds here.

set "RUN_TITLE=Build Frameworks"
set "RUN_MODULE=scripts.download.frameworks.build_frameworks"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
