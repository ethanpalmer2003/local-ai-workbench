@echo off
setlocal
set "AI_ROOT=C:\AI"
pushd "%AI_ROOT%"
title Strata Pi
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.strata.strata_pi %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %LAUNCH_EXIT%
