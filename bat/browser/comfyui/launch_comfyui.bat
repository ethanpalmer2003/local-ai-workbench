@echo off
setlocal
set "ATTENTION=sage"
set "CACHE_MODE=none"
set "SMART_MEMORY=0"
:: Default 0111: SMART_MEMORY / FA_AUTOTUNE / DISABLE_TRITON / DYNAMIC_VRAM.
:: Keep smart memory off; the other three settings need isolated benchmark comparisons.
set "FA_AUTOTUNE=1"
set "DISABLE_TRITON=1"
set "DYNAMIC_VRAM=1"
call "%~dp0comfyui_bootstrap.bat" %*
exit /b %ERRORLEVEL%
