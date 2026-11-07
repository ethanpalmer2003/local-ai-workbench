@echo off
setlocal
pushd C:\AI
title KoboldCpp Language Practice (no model, llama.cpp)
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.koboldcpp.kobold --llm external --model llamacpp/gemma-4-E4B-it-Q4_0 --usage-profile shared --transcription-engine audiocpp-nemotron --speech-engine kokoro-audiocpp --practice-ui %*
set "PRACTICE_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %PRACTICE_EXIT%
