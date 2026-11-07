@echo off
setlocal
"C:\AI\scripts\.venv\Scripts\ruff.exe" format --config "C:\AI\pyproject.toml" "C:\AI\scripts" %*
exit /b %ERRORLEVEL%
