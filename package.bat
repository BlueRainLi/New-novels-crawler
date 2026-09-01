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

REM zstandard is required for Nuitka onefile compression. Without it the
REM payload stays uncompressed and the .exe ends up ~2x larger.
python -c "import zstandard" 2>nul
if %ERRORLEVEL% neq 0 (
    echo [INFO] installing zstandard ^(for onefile compression^) ...
    pip install zstandard -q
    if !ERRORLEVEL! neq 0 (
        echo [WARN] zstandard install failed, onefile will NOT be compressed
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

REM Size trimming notes (see package.bat.bak for the untrimmed original):
REM   - "ebooklib.plugins" is what dragged in pygments (~20MB, 323 modules).
REM     ebooklib never imports its own plugins package; plugins are passed in
REM     via options["plugins"], so both are dead weight here.
REM   - Pillow is pulled in by ttkbootstrap. Nuitka reads PIL.Image._plugins and
REM     force-includes every plugin as an implicit import, which is where the
REM     7.6MB _avif.pyd comes from. Must use --nofollow-import-to here, because
REM     --noinclude-dlls is NOT applied to extension modules (see
REM     nuitka/freezer/IncludedEntryPoints.py: addExtensionModuleEntryPoint
REM     appends straight to standalone_entry_points and skips the filter).
REM     Verified --noinclude-dlls=*_avif* has no effect on it.
REM   - Do NOT exclude PIL._imagingft (2.1MB): ttkbootstrap/style.py calls
REM     ImageFont.truetype() at line ~4438, which needs it.
REM   - Do NOT exclude curl_cffi.requests.websockets or curl_cffi.aio: both are
REM     imported at module level by curl_cffi/__init__.py, so excluding them
REM     makes the import fail at runtime.

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
    --nofollow-import-to=ebooklib.plugins ^
    --nofollow-import-to=pygments ^
    --nofollow-import-to=PIL._avif ^
    --nofollow-import-to=PIL._imagingcms ^
    --nofollow-import-to=PIL._webp ^
    --nofollow-import-to=lxml.objectify ^
    --nofollow-import-to=IPython ^
    --nofollow-import-to=debugpy ^
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
