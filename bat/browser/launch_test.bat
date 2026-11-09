@echo off
set "RUN_TITLE=Speech Workspace Test"
set "RUN_MODULE=scripts.launchers.llamacpp.language_practice"
call "%~dp0..\_run.bat" --ui test %*
exit /b %ERRORLEVEL%
