@echo off
setlocal
pushd "C:\AI"
title ASR Test
"scripts\.venv\Scripts\python.exe" -m scripts.launchers.llamacpp.language_practice --ui test --test-mode asr --no-tts %*
set "TEST_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %TEST_EXIT%
