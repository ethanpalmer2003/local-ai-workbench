@echo off
set "RUN_TITLE=ASR Comparison"
set "RUN_MODULE=scripts.benchmarks.asr.asr_resident_compare"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
