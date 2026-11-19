@echo off
set "RUN_TITLE=Duplicate Blocks"
set "RUN_MODULE=scripts.review.checks.duplicates"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
