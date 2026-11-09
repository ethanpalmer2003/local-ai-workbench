@echo off
setlocal
rem Report source/newer status, then fetch missing active files the catalog expects.
rem Existing complete files are skipped, so nothing is re-downloaded. Flags apply to the check.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Model Updates
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.updates %*
set "CHECK_EXIT=%ERRORLEVEL%"
echo.
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.download_catalog --active --download
set "DOWNLOAD_EXIT=%ERRORLEVEL%"
popd
echo.
pause
if %CHECK_EXIT% neq 0 exit /b %CHECK_EXIT%
exit /b %DOWNLOAD_EXIT%
