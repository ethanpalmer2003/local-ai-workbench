@echo off
setlocal
pushd "C:\AI"
title Model sync check
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.model_sync %*
set "CHECK_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %CHECK_EXIT%
