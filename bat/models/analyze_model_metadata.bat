@echo off
setlocal
pushd C:\AI
"scripts\.venv\Scripts\python.exe" -m scripts.download.models.analyze_model %*
set "ANALYZE_EXIT=%ERRORLEVEL%"
popd
exit /b %ANALYZE_EXIT%
