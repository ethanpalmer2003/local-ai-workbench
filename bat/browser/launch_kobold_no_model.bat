@echo off
setlocal
pushd "C:\AI"
title KoboldCpp character chat (no model, llama.cpp)
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.koboldcpp.kobold --llm external --usage-profile shared %*
set "LAUNCH_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %LAUNCH_EXIT%
