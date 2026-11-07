@echo off
setlocal
rem Native launcher/proxy wiring: starts the real launchers, generates output, stops owned processes.
rem Refuses if a user session already holds a service port.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Live Launchers
"scripts\.venv\Scripts\python.exe" -m scripts.tests.run --suite launchers %*
set "TEST_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %TEST_EXIT%
