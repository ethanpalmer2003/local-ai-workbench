@echo off
setlocal
pushd "C:\AI"
title Model Downloads
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.cli_download %*
set "DOWNLOAD_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %DOWNLOAD_EXIT%
