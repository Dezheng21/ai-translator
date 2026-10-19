@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
for %%I in ("%SCRIPT_DIR%..\..") do set "APP_DIR=%%~fI"
cd /d "%APP_DIR%"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%APP_DIR%\translate_ai_gui.py"
  if errorlevel 1 goto error
  goto done
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%APP_DIR%\translate_ai_gui.py"
  if errorlevel 1 goto error
  goto done
)

echo Python 3 was not found. Please install Python 3 and try again.
pause
exit /b 1

:error
echo.
echo The AI translator could not start. Error code: %errorlevel%
echo Please copy the message above if you need help.
pause
exit /b %errorlevel%

:done
endlocal
