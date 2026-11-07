@echo off
setlocal
cd /d C:\AI
rem Framework-local CLI; the global npm install is not required.
set "CMDC=C:\AI\frameworks\coding_agents\commandcode\node_modules\.bin\cmdc.cmd"
if not exist "%CMDC%" (
  echo Command Code CLI is not installed.
  echo Run: C:\AI\bat\update_frameworks.bat --only coding_agents/commandcode
  exit /b 1
)
call "%CMDC%" -c %*
exit /b %ERRORLEVEL%
