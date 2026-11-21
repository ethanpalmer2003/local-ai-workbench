@echo off
rem Check all selected tools, print grouped plan, then apply eligible updates.
rem A source build with no install directory yet is offered once at the end.
rem Flags: --skip-comfyui, --check-only, --only name-or-group, --build-missing
rem Runs through the shared progress bar; every line the updater prints is kept.
rem Double-clicking this batch is the request, so the ten-minute update starts without its prompt;
rem a terminal that cannot answer a prompt would otherwise hold the stage until its cap and kill it.

set "RUN_TITLE=Framework Updates"
set "RUN_MODULE=scripts.tools.stage_runner"
call "%~dp0_run.bat" scripts.download.frameworks.update_frameworks --stage-known frameworks --yes %*
exit /b %ERRORLEVEL%
