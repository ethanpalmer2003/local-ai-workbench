@echo off
setlocal
rem Check all selected tools, print grouped plan, then apply eligible updates.
rem Flags: --skip-comfyui, --check-only, --only name-or-group

set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"
title Framework Updates
"scripts\.venv\Scripts\python.exe" -m scripts.download.frameworks.update_frameworks %*
set "UPDATE_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %UPDATE_EXIT%
