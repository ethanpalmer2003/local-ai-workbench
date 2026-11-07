@echo off
cd /d C:\AI
C:\AI\scripts\.venv\Scripts\python.exe -m scripts.benchmarks.tts_engines.resident %*
exit /b %ERRORLEVEL%
