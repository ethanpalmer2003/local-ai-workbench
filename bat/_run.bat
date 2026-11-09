@echo off
rem Shared batch runner. Callers set RUN_TITLE and RUN_MODULE before calling it; the call path is
rem the current folder from the bat root and the parent folder from a subfolder.
rem It owns the venv path, working directory, title, pause and exit code.
setlocal
if not defined RUN_MODULE (
  echo [FAIL] _run.bat needs RUN_MODULE
  exit /b 2
)
if not defined RUN_TITLE set "RUN_TITLE=C:\AI"
pushd "C:\AI"
title %RUN_TITLE%
"scripts\.venv\Scripts\python.exe" -m %RUN_MODULE% %*
set "RUN_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %RUN_EXIT%
