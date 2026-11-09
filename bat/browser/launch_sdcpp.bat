@echo off
set "RUN_TITLE=SdCpp Browser UI"
set "RUN_MODULE=scripts.launchers.sdcpp.proxy"
call "%~dp0..\_run.bat" --open-test %*
exit /b %ERRORLEVEL%
