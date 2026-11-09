@echo off
set "RUN_TITLE=Model Metadata"
set "RUN_MODULE=scripts.download.models.analyze_model"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
