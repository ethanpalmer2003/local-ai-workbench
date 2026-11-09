@echo off
setlocal
rem Report source/newer status, then fetch missing active files the catalog expects.
rem Existing complete files are skipped, so nothing is re-downloaded. Flags apply to the check.
rem Both stages run behind the shared progress bar; their output is kept.

set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"
title Model Updates
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.update_models %*
set "UPDATE_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %UPDATE_EXIT%
