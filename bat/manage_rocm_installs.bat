@echo off
setlocal
rem Inventory ROCm installs on this machine: location, kind, version, size and project references.
rem Read-only. --json prints machine-readable rows, --no-sizes skips walking each tree.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title ROCm Inventory
"scripts\.venv\Scripts\python.exe" -m scripts.tools.rocm_inventory %*
set "INVENTORY_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %INVENTORY_EXIT%
