@echo off
setlocal
pushd "C:\AI"
title Strata vs Avalon
"scripts\.venv\Scripts\python.exe" -m scripts.benchmarks.inference_engines.benchmark_strata_avalon %* 2>&1 | "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$input | Tee-Object -FilePath 'scripts\benchmarks\output\run_strata_avalon.log'"
set "BENCH_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %BENCH_EXIT%
