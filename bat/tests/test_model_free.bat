@echo off
setlocal
rem Model-free regression suite: no VRAM, no model processes, no port kills.
set "AI_ROOT=C:\AI"

for %%A in (%*) do (
  if /I "%%A"=="--live" (
    echo Use test_live_launchers.bat or test_live_backends.bat for VRAM workflows.
    exit /b 2
  )
)

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Model-Free Tests
"scripts\.venv\Scripts\python.exe" -m scripts.tests.run %*
set "TEST_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %TEST_EXIT%
