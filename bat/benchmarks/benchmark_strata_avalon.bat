@echo off
rem Strata vs Avalon on the same Strata weights: prefill, decode and TTFT. --engines, --samples pass through.
rem Reports land under scripts\benchmarks\output\; the module owns the log, so nothing is teed here.

set "RUN_TITLE=Strata vs Avalon"
set "RUN_MODULE=scripts.benchmarks.inference_engines.benchmark_strata_avalon"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
