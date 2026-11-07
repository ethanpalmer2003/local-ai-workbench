@echo off
setlocal
rem Both native suites: launcher/proxy wiring, then every backend probe.
rem Refuses if a user session already holds a service port.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Live All
"scripts\.venv\Scripts\python.exe" -m scripts.tests.run --suite all %*
set "TEST_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %TEST_EXIT%
