@echo off
rem Check all selected tools, print grouped plan, then apply eligible updates.
rem Flags: --skip-comfyui, --check-only, --only name-or-group
rem Runs through the shared progress bar; every line the updater prints is kept.

set "RUN_TITLE=Framework Updates"
set "RUN_MODULE=scripts.tools.stage_runner"
call "%~dp0_run.bat" scripts.download.frameworks.update_frameworks --stage-known frameworks %*
exit /b %ERRORLEVEL%
