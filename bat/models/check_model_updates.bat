@echo off
setlocal
rem Check catalog model sources against Hugging Face and hint at newer releases.
rem Missing or unreachable pinned files fail; size drift and newer versions are reported.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Model Updates
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.updates %*
set "UPDATE_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %UPDATE_EXIT%
