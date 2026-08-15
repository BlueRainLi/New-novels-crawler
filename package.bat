@echo off
chcp 65001 >nul
title package novels crawler

setlocal enabledelayedexpansion

set MAIN_SCRIPT=gui.py
set OUTPUT_DIR=dist
set MODE=onefile
set ICON_FILE=
set EXTRA_ARGS=

REM parallel jobs; leave empty to use all CPU cores (100%%)
REM set to half of CPU cores to reduce load, e.g. set JOBS=4
set JOBS=4

if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
) else (
    echo [ERROR] .venv not found
    pause
    exit /b 1
)

python -c "import nuitka" 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] installing nuitka ...
    pip install nuitka -q
    if !ERRORLEVEL! neq 0 (
        echo [ERROR] nuitka install failed
        pause
        exit /b 1
    )
)

if not exist "%MAIN_SCRIPT%" (
    echo [ERROR] %MAIN_SCRIPT% not found
    pause
    exit /b 1
)

set MODE_ARGS=
if /i "%MODE%"=="onefile" (
    set MODE_ARGS=--onefile
) else (
    set MODE_ARGS=--standalone
)

set ICON_ARGS=
if not "%ICON_FILE%"=="" (
    if exist "%ICON_FILE%" (
        set ICON_ARGS=--windows-icon-from-ico="%ICON_FILE%"
    )
)

set PLUGIN_ARGS=
if /i "%MAIN_SCRIPT%"=="gui.py" (
    set PLUGIN_ARGS=--enable-plugin=tk-inter
)
if /i "%MAIN_SCRIPT%"=="guiQt.py" (
    set PLUGIN_ARGS=--enable-plugin=pyside6
)

REM init MSVC environment if not in PATH
where cl.exe >nul 2>nul
if %ERRORLEVEL% neq 0 (
    if exist "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" (
        "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe" -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath > %TEMP%\vs_path.txt
        set /p VSINSTALL=<%TEMP%\vs_path.txt
        del %TEMP%\vs_path.txt
    )
    if not defined VSINSTALL (
        set "VSINSTALL=C:\Program Files (x86)\Microsoft Visual Studio\18\BuildTools"
    )
    if exist "!VSINSTALL!\VC\Auxiliary\Build\vcvars64.bat" (
        call "!VSINSTALL!\VC\Auxiliary\Build\vcvars64.bat"
    ) else (
        echo [WARN] MSVC not found, Nuitka may fall back to zig compiler
    )
)

echo ============================================
echo  packaging %MAIN_SCRIPT%  mode=%MODE%
echo ============================================
echo.

REM NOTE: --windows-console-mode=disable is intentionally NOT passed,
REM so the .exe keeps a console window (handy for debugging).
REM To hide the console instead, add the option to the command below.

python -m nuitka ^
    %MODE_ARGS% ^
    %PLUGIN_ARGS% ^
    %ICON_ARGS% ^
    --output-dir="%OUTPUT_DIR%" ^
    --assume-yes-for-downloads ^
    --lto=yes ^
    --disable-ccache ^
    --show-memory ^
    --show-progress ^
    --follow-imports ^
    --include-package=curl_cffi ^
    --include-package=ebooklib ^
    --nofollow-import-to=tkinter.test ^
    --nofollow-import-to=pytest ^
    --nofollow-import-to=unittest ^
    --nofollow-import-to=distutils ^
    --nofollow-import-to=setuptools ^
    --nofollow-import-to=pydoc ^
    --nofollow-import-to=doctest ^
    --jobs=%JOBS% ^
    %EXTRA_ARGS% ^
    "%MAIN_SCRIPT%"

if %ERRORLEVEL% equ 0 (
    echo.
    echo [SUCCESS] build complete
    if /i "%MODE%"=="standalone" (
        echo           output in %OUTPUT_DIR%\%MAIN_SCRIPT:~0,-3%.dist\
    ) else (
        echo           output in %OUTPUT_DIR%\
    )
) else (
    echo.
    echo [FAILED] build error, check logs above
)

pause
endlocal
