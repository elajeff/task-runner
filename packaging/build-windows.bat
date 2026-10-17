@echo off
setlocal
cd /d "%~dp0\.."

echo task runner Windows build
echo =========================
echo Builds the Windows application bundle locally. It does not sign the executable.
echo Python 3.13 x64 and an internet connection are required for the first build.
echo Detailed output is saved to build-windows.log.
echo.

where powershell.exe >nul 2>&1
if errorlevel 1 goto :no_powershell

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%CD%\packaging\build-windows.ps1"
set "BUILD_EXIT_CODE=%ERRORLEVEL%"
if not "%BUILD_EXIT_CODE%"=="0" (
    echo.
    echo BUILD FAILED. The error should be shown above.
    echo Log file: "%CD%\build-windows.log"
) else (
    echo.
    echo BUILD SUCCEEDED.
    echo App folder: "%CD%\dist\task-runner"
    echo Executable: "%CD%\dist\task-runner\task-runner.exe"
    echo Release ZIP: "%CD%\dist\task-runner-windows-x64.zip"
)
echo.
echo This window will stay open so you can read the result.
pause
exit /b %BUILD_EXIT_CODE%

:no_powershell
echo ERROR: Windows PowerShell could not be found. It is normally included with Windows 10 and 11.
echo.
pause
exit /b 1
