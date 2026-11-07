@echo off
setlocal
pushd "C:\AI"
title Coding Agent Benchmarks
rem - No arguments runs the quick check: one task, one repeat. Pass arguments for a wider matrix.
if "%~1"=="" (
  "scripts\.venv\Scripts\python.exe" -m scripts.benchmarks.coding_agents.shared.benchmark_agents --suite polyglot --tasks proverb --repeats 1
) else (
  "scripts\.venv\Scripts\python.exe" -m scripts.benchmarks.coding_agents.shared.benchmark_agents %*
)
set "BENCH_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %BENCH_EXIT%
