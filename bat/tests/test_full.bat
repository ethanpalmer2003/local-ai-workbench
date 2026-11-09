@echo off
setlocal
rem Full validation: the gate, the model-free suite and both live suites, in one progress bar.
rem Live stages skip when their sources and installations are unchanged; --force reruns them.
rem A stage that ends above its expected range is reported as slow.
set "AI_ROOT=C:\AI"

rem -m needs the package root's parent as cwd
pushd "%AI_ROOT%"

title Full Validation
"scripts\.venv\Scripts\python.exe" -m scripts.tests.validate %*
set "TEST_EXIT=%ERRORLEVEL%"
popd
echo.
pause
exit /b %TEST_EXIT%
