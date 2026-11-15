@echo off
rem Format the Python this change touched; --all formats the whole repository.
setlocal
title Python Format
pushd C:\AI
".venv\Scripts\python.exe" -m scripts.review.format_py %*
set "FORMAT_EXIT=%ERRORLEVEL%"
popd
exit /b %FORMAT_EXIT%
