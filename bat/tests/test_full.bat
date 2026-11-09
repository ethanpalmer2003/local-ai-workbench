@echo off
rem Full validation: update frameworks first, then the gate, the model-free suite and both live
rem suites, in one progress bar. --no-update skips the framework preflight; --force reruns live suites.
rem A stage that ends above its expected range is reported as slow.

set "RUN_TITLE=Full Validation"
set "RUN_MODULE=scripts.tests.validate"
call "%~dp0..\_run.bat" %*
exit /b %ERRORLEVEL%
