@echo off
set "RUN_TITLE=TTS Speed"
set "RUN_MODULE=scripts.benchmarks.tts_engines.resident"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
