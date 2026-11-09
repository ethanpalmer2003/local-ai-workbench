@echo off
rem Bring catalog models to their newest release: check versioned families, download the newer file,
rem rewrite references and move the old weights to trash. --dry-run previews the swaps.

set "RUN_TITLE=Model Updates"
set "RUN_MODULE=scripts.download.models.update_models"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
