@echo off
set "RUN_TITLE=Model sync check"
set "RUN_MODULE=scripts.download.models.model_sync"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
