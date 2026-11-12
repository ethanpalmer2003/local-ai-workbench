@echo off
setlocal
title Python Format
pushd C:\AI
".venv\Scripts\ruff.exe" format --config "C:\AI\pyproject.toml" . %*
set "FORMAT_EXIT=%ERRORLEVEL%"
popd
exit /b %FORMAT_EXIT%
