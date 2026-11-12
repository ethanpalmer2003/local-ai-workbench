@echo off
set "RUN_TITLE=KoboldCpp Language Practice (built-in Whisper)"
set "RUN_MODULE=scripts.launchers.koboldcpp.kobold"
call "%~dp0..\_run.bat" --usage-profile shared --transcription-engine embedded --speech-engine audiocpp --practice-ui %*
exit /b %ERRORLEVEL%
