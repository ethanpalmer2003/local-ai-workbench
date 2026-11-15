@echo off
set "RUN_TITLE=Markdown Duplicates"
set "RUN_MODULE=scripts.review.similarity"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
