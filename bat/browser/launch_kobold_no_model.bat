@echo off
set "RUN_TITLE=KoboldCpp character chat (no model, llama.cpp)"
set "RUN_MODULE=scripts.launchers.koboldcpp.kobold"
call "%~dp0..\_run.bat" --llm external --usage-profile shared %*
exit /b %ERRORLEVEL%
