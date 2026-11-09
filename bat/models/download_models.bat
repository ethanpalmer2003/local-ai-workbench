@echo off
rem Download catalog models. With no arguments, fetch only the active files that are missing.
rem Never looks for newer versions; update_models does that. Arbitrary repo/url/file flags pass through.

set "RUN_TITLE=Model Downloads"
set "RUN_MODULE=scripts.download.models.download_models"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
