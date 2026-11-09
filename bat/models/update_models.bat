@echo off
setlocal
rem Bring catalog models to their newest release: check versioned families, download the newer file,
rem rewrite references and move the old weights to trash. --dry-run previews the swaps.
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
