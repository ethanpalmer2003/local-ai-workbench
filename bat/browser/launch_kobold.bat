@echo off
set "RUN_TITLE=KoboldCpp Launcher"
set "RUN_MODULE=scripts.launchers.koboldcpp.kobold"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
