@echo off
setlocal
pushd "C:\AI"
title Model server comparison
"scripts\.venv\Scripts\python.exe" -m scripts.benchmarks.shared.framework_compare %* 2>&1 | "C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -Command "$input | Tee-Object -FilePath 'scripts\benchmarks\output\shared\framework_compare.log'"
set "BENCH_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %BENCH_EXIT%
