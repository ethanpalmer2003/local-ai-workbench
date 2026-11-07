@echo off
cd /d C:\AI
C:\AI\scripts\.venv\Scripts\python.exe -m scripts.benchmarks.asr.asr_resident_compare %*
exit /b %ERRORLEVEL%
