@echo off
setlocal
pushd "C:\AI"
title Speech Workspace Test
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.llamacpp.language_practice --ui test %*
set "WORKSPACE_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %WORKSPACE_EXIT%
