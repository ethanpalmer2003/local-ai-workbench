@echo off
set "RUN_TITLE=ASR Test"
set "RUN_MODULE=scripts.launchers.llamacpp.language_practice"
call "%~dp0..\_run.bat" --ui test --test-mode asr --no-tts %*
exit /b %ERRORLEVEL%
