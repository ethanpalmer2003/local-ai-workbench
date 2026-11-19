@echo off
rem Practice stack vs Lemonade vs KoboldCpp: chat, Kokoro speech and recognition, one stack at a time.
rem Reports land under scripts\benchmarks\output\; the module owns the log, so nothing is teed here.

set "RUN_TITLE=Language practice comparison"
set "RUN_MODULE=scripts.benchmarks.shared.framework_compare"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
