@echo off
set "RUN_TITLE=llama.cpp Language Practice"
set "RUN_MODULE=scripts.launchers.llamacpp.language_practice"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
