@echo off
setlocal
pushd C:\AI
title KoboldCpp Language Practice
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.koboldcpp.kobold --usage-profile shared --transcription-engine audiocpp-nemotron --speech-engine kokoro-audiocpp --practice-ui %*
set "PRACTICE_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %PRACTICE_EXIT%
