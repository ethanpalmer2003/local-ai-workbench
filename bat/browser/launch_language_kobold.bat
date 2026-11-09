@echo off
set "RUN_TITLE=KoboldCpp Language Practice"
set "RUN_MODULE=scripts.launchers.koboldcpp.kobold"
call "%~dp0..\_run.bat" --usage-profile shared --transcription-engine audiocpp-nemotron --speech-engine kokoro-audiocpp --practice-ui %*
exit /b %ERRORLEVEL%
