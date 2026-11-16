@echo off
set "RUN_TITLE=Code Duplicates"
set "RUN_MODULE=scripts.review.checks.similarity --code"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
