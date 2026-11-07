@echo off
setlocal
rem Native backend probes: each engine/model loads and answers. No launcher/proxy wiring.
rem `--only NAME...` narrows the probe list. Refuses if a user session holds a service port.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Live Backends
"scripts\.venv\Scripts\python.exe" -m scripts.tests.run --suite backends %*
set "TEST_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %TEST_EXIT%
