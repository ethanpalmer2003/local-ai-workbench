@echo off
set "RUN_TITLE=Model Languages"
set "RUN_MODULE=scripts.config.models.model_languages"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
