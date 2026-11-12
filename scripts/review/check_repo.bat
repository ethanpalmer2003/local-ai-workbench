@echo off
setlocal
title Repository Review
pushd C:\AI
".venv\Scripts\python.exe" -m scripts.review
set "REVIEW_EXIT=%ERRORLEVEL%"
popd
exit /b %REVIEW_EXIT%
