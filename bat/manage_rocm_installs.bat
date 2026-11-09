@echo off
rem Inventory ROCm installs on this machine: location, kind, version, size and project references.
rem Read-only. --json prints machine-readable rows, --no-sizes skips walking each tree.

set "RUN_TITLE=ROCm Inventory"
set "RUN_MODULE=scripts.tools.rocm_inventory"
call "%~dp0_run.bat" %*
exit /b %ERRORLEVEL%
