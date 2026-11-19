@echo off
set "RUN_TITLE=Handoff Bundle"
set "RUN_MODULE=scripts.review.handoff"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
