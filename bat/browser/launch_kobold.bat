@echo off
setlocal
pushd "C:\AI"
title KoboldCpp Launcher
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.koboldcpp.kobold %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %LAUNCH_EXIT%
