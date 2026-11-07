@echo off
setlocal
pushd "C:\AI"
title Build Frameworks
rem - Default: one new terminal per source build. --foreground builds here.
"scripts\.venv\Scripts\python.exe" -m scripts.download.frameworks.build_frameworks %*
set "BUILD_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %BUILD_EXIT%
