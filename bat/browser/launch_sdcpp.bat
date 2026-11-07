@echo off
setlocal
pushd "C:\AI"
title SdCpp Browser UI
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.sdcpp.proxy --open-test %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %LAUNCH_EXIT%
