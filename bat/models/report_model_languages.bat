@echo off
setlocal
pushd C:\AI
"scripts\.venv\Scripts\python.exe" -m scripts.config.models.model_languages %*
set "LANGUAGES_EXIT=%ERRORLEVEL%"
popd
exit /b %LANGUAGES_EXIT%
