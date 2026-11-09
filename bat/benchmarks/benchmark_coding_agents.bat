@echo off
rem - No arguments runs the quick check: one task, one repeat. Pass arguments for a wider matrix.

set "RUN_TITLE=Coding Agent Benchmarks"
set "RUN_MODULE=scripts.benchmarks.coding_agents.shared.benchmark_agents"
call "%~dp0..\_run.bat" --suite polyglot --tasks proverb --repeats 1
exit /b %ERRORLEVEL%
