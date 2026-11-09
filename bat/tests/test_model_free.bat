@echo off
rem Model-free regression suite: no VRAM, no model processes, no port kills.

set "RUN_TITLE=Model-Free Tests"
set "RUN_MODULE=scripts.tests.run"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
