@echo off
setlocal
rem Download catalog models. With no arguments, fetch only the active files that are missing.
rem Never looks for newer versions; update_models does that. Arbitrary repo/url/file flags pass through.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Model Downloads
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.download_models %*
set "DOWNLOAD_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %DOWNLOAD_EXIT%
