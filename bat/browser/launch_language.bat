@echo off
setlocal
pushd C:\AI
title llama.cpp Language Practice
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.llamacpp.language_practice %*
set "PRACTICE_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %PRACTICE_EXIT%
