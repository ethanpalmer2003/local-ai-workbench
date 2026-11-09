@echo off
set "RUN_TITLE=LlamaCpp Test"
set "RUN_MODULE=scripts.launchers.llamacpp.language_practice"
call "%~dp0..\_run.bat" --ui test --test-mode llm --no-tts %*
exit /b %ERRORLEVEL%
