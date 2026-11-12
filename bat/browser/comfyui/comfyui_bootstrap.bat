@echo off
setlocal enabledelayedexpansion

:: ============================================================
:: Install location (script can live anywhere)
:: ============================================================
pushd "C:\AI"
for /f "delims=" %%I in ('.venv\Scripts\python.exe -c "from scripts.config import project_config as p; print(p.COMFYUI_ROCM_DIR)"') do set "COMFYUI_ROCM_DIR=%%I"
for /f "delims=" %%I in ('.venv\Scripts\python.exe -c "from scripts.config import project_config as p; print(p.OUTPUT_DIR)"') do set "COMFYUI_OUTPUT_DIR=%%I"
for /f "delims=" %%I in ('.venv\Scripts\python.exe -c "from scripts.config import sync_configs as s; print(s.installed_node())"') do set "COMFYUI_NODE_FILE=%%I"
.venv\Scripts\python.exe -m scripts.config.sync_configs --only comfyui --apply
if errorlevel 1 (
    echo [FAIL] ComfyUI configuration sync failed. Startup stopped.
    popd
    pause
    exit /b 1
)
popd
if not defined COMFYUI_ROCM_DIR exit /b 1

pushd "%COMFYUI_ROCM_DIR%"
if errorlevel 1 (
    echo Cannot access %COMFYUI_ROCM_DIR%
    pause
    exit /b 1
)

title ComfyUI

set PYTHONUTF8=1
:: Keep the venv isolated from user-level site-packages that could shadow python_env's
set "PYTHONNOUSERSITE=1"

:: ANSI color support (Windows 10+)
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
set "GREEN=%ESC%[32m"
set "YELLOW=%ESC%[33m"
set "CYAN=%ESC%[36m"
set "RESET=%ESC%[0m"

:: read installed version from hash file
set "HASH_FILE=%COMFYUI_ROCM_DIR%\.last_update_hash"
set "VERSION=unknown"
if exist "!HASH_FILE!" set /p VERSION=<"!HASH_FILE!"
set "VERSION=!VERSION:~0,10!"

:: paths
set "PYTHON_DIR=%COMFYUI_ROCM_DIR%\python_env"
set "PATH=%PYTHON_DIR%;%PYTHON_DIR%\Scripts;%PATH%"

if not exist "%PYTHON_DIR%\python.exe" (
    echo [ERROR] python.exe not found at %PYTHON_DIR%\python.exe
    popd
    pause
    exit /b 1
)

:: ------------------------- installed node contract --------------------------- ::
if not defined COMFYUI_NODE_FILE (
    echo [FAIL] Could not resolve the installed ComfyUI node path. Startup stopped.
    popd
    pause
    exit /b 1
)
echo %GREEN%[INFO]%RESET% Checking the installed ComfyUI node...
"%PYTHON_DIR%\python.exe" "C:\AI\scripts\config\comfyui\verify_node.py" "!COMFYUI_NODE_FILE!"
if errorlevel 1 (
    echo [FAIL] The installed ComfyUI node does not load under this interpreter. Startup stopped.
    popd
    pause
    exit /b 1
)

echo %GREEN%[INFO]%RESET% Initializing rocm-sdk...
"%PYTHON_DIR%\python.exe" -m rocm_sdk init >nul 2>&1
if errorlevel 1 (
    echo %YELLOW%[WARN]%RESET% rocm-sdk init failed. ROCm may not be set up correctly.
)

set "HIP_PATH="
for /f "delims=" %%i in ('"%PYTHON_DIR%\python.exe" -m rocm_sdk path --root') do set "HIP_PATH=%%i"
set "ROCM_PATH=%HIP_PATH%"

:: ------------------- detect GPU architecture ---------------- ::
echo %GREEN%[INFO]%RESET% Detecting GPU architecture...
set "GPU_ARCH="
for /f "delims=" %%A in ('"%PYTHON_DIR%\python.exe" "%COMFYUI_ROCM_DIR%\detect_gpu.py" 2^>nul') do set "GPU_ARCH=%%A"
set "IS_LEGACY_GPU=0"
if /I "!GPU_ARCH:~0,6!"=="gfx101" set "IS_LEGACY_GPU=1"
if /I "!GPU_ARCH:~0,6!"=="gfx103" set "IS_LEGACY_GPU=1"

set "IS_RDNA4_GPU=0"
if /I "!GPU_ARCH:~0,6!"=="gfx120" set "IS_RDNA4_GPU=1"

if "!GPU_ARCH!"=="" (
    echo %YELLOW%[WARN]%RESET% Could not detect GPU architecture.
) else (
    echo %GREEN%[INFO]%RESET% GPU arch: %CYAN%!GPU_ARCH!%RESET%
)

:: disable Flash and MemEff SDP backends on RDNA1/2 only
if "!IS_LEGACY_GPU!"=="1" (
    echo %GREEN%[INFO]%RESET% Legacy GPU detected - applying RDNA1/2 SDP overrides.
    set TORCH_BACKENDS_CUDA_FLASH_SDP_ENABLED=0
    set TORCH_BACKENDS_CUDA_MEM_EFF_SDP_ENABLED=0
    set TORCH_BACKENDS_CUDA_MATH_SDP_ENABLED=1
) else (
    set TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=1
)

:: ------------------------- cache and database paths ------------------------ ::
set "PYTORCH_TUNABLEOP_CACHE_DIR=%COMFYUI_ROCM_DIR%\tunableop-cache"
set "TRITON_CACHE_DIR=%COMFYUI_ROCM_DIR%\triton-cache"

if not exist "%TRITON_CACHE_DIR%" mkdir "%TRITON_CACHE_DIR%"
if not exist "%PYTORCH_TUNABLEOP_CACHE_DIR%" mkdir "%PYTORCH_TUNABLEOP_CACHE_DIR%"

:: Skip MIOpen and ROCBlas paths for gfx1100 (RDNA3) - not present atm
if /I NOT "!GPU_ARCH!"=="gfx1100" (
    set "MIOPEN_SYSTEM_DB_PATH=%PYTHON_DIR%\Lib\site-packages\_rocm_sdk_devel\bin"
    set "ROCBLAS_TENSILE_DB_PATH=%PYTHON_DIR%\Lib\site-packages\_rocm_sdk_devel\bin\rocblas"
    set "ROCBLAS_TENSILE_LIBPATH=%PYTHON_DIR%\Lib\site-packages\_rocm_sdk_devel\bin\rocblas\library"
)

:: ---------------------- advanced settings (miopen, triton etc.) ------------- ::
set COMFYUI_ENABLE_MIOPEN=0
set FLASH_ATTENTION_TRITON_AMD_ENABLE=TRUE
if "!FA_AUTOTUNE!"=="1" set FLASH_ATTENTION_TRITON_AMD_AUTOTUNE=TRUE
if "!FA_AUTOTUNE!"=="0" set FLASH_ATTENTION_TRITON_AMD_AUTOTUNE=FALSE
set MIOPEN_FIND_ENFORCE=1
set MIOPEN_FIND_MODE=2
set MIOPEN_DEBUG_DISABLE_FIND_DB=0
set MIOPEN_SEARCH_CUTOFF=1
set MIOPEN_ENABLE_LOGGING=0
set MIOPEN_LOG_LEVEL=0
set MIOPEN_ENABLE_LOGGING_CMD=0
set TRITON_PRINT_AUTOTUNING=0
set TRITON_CACHE_AUTOTUNING=0

:: if you get "torch.AcceleratorError: CUDA error: invalid kernel file"
:: remove the "::" from the line below
:: set HIP_VISIBLE_DEVICES=1

:: ----------------- startup options ------------------------------------------ ::
:: Variables you can set before calling this script:
::   DISABLE_TRITON=1   DYNAMIC_VRAM=1   SMART_MEMORY=0
::   ATTENTION=flash|sage|pytorch|ck   (ck = comfy-kitchen attention, default on RDNA4)
::   CACHE_MODE=ram|none|lru           (lru = --cache-lru 20)
set "PARAMS=--disable-partner-nodes --disable-pinned-memory --enable-manager --enable-manager-legacy-ui --output-directory "!COMFYUI_OUTPUT_DIR!""

if "!DISABLE_TRITON!"=="1" set "PARAMS=!PARAMS! --disable-triton-backend"
if "!DISABLE_TRITON!"=="0" set "PARAMS=!PARAMS! --enable-triton-backend"
if "!DYNAMIC_VRAM!"=="1"   set "PARAMS=!PARAMS! --enable-dynamic-vram"
if "!DYNAMIC_VRAM!"=="0"   set "PARAMS=!PARAMS! --disable-dynamic-vram"

:: RDNA4 defaults to ck-attention unless you picked another attention mode
if "!IS_RDNA4_GPU!"=="1" if "!ATTENTION!"=="" set "ATTENTION=ck"

if /I "!ATTENTION!"=="flash"   set "PARAMS=!PARAMS! --use-flash-attention"
if /I "!ATTENTION!"=="sage"    set "PARAMS=!PARAMS! --use-sage-attention"
if /I "!ATTENTION!"=="pytorch" set "PARAMS=!PARAMS! --use-pytorch-cross-attention"
if /I "!ATTENTION!"=="ck"      set "PARAMS=!PARAMS! --use-ck-attention"

if /I "!CACHE_MODE!"=="ram"  set "PARAMS=!PARAMS! --cache-ram"
if /I "!CACHE_MODE!"=="none" set "PARAMS=!PARAMS! --cache-none"
if /I "!CACHE_MODE!"=="lru"  set "PARAMS=!PARAMS! --cache-lru 20"

if "!SMART_MEMORY!"=="0" set "PARAMS=!PARAMS! --disable-smart-memory"

:: quad-cross is better for older generation GPUs
if "!IS_LEGACY_GPU!"=="1" set "PARAMS=!PARAMS! --use-quad-cross-attention"

:: --------------------------- keep tracked packages up to date ---------------- ::
echo %GREEN%[INFO]%RESET% Syncing tracked packages from requirements.txt...
for %%P in (comfyui-frontend-package comfyui-workflow-templates comfyui-embedded-docs comfy-kitchen comfy-aimdo av) do (
    for /f "tokens=1,2 delims==" %%A in ('findstr /i "^%%P==" "%COMFYUI_ROCM_DIR%\requirements.txt"') do (
        "%PYTHON_DIR%\python.exe" -m pip show %%A 2>nul | findstr /i "^Version:" > "%TEMP%\pkgver.txt"
        set INSTALLED=
        for /f "tokens=2" %%V in (%TEMP%\pkgver.txt) do set INSTALLED=%%V
        if not "!INSTALLED!"=="%%B" (
            "%PYTHON_DIR%\python.exe" -m pip install "%%A==%%B" --quiet 2>nul
            echo %YELLOW%[UPDATED]%RESET% %%A  !INSTALLED! ^> %%B
        )
    )
)

:: ------------------------------- launch -------------------------------------- ::
set "DISPLAY_PARAMS=!PARAMS:--=!"
echo %GREEN%[INFO]%RESET% [comfyui-rocm] %CYAN%!VERSION!%RESET% starting with: [ %CYAN%!DISPLAY_PARAMS!%RESET% ]
echo.
"%PYTHON_DIR%\python.exe" main.py !PARAMS! %*
set "LAUNCH_EXIT=!ERRORLEVEL!"
popd

pause
exit /b %LAUNCH_EXIT%
