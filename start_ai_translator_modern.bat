@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if not errorlevel 1 (
  py -3 "%~dp0translate_ai_web.py"
  if errorlevel 1 goto error
  goto done
)

where python >nul 2>nul
if not errorlevel 1 (
  python "%~dp0translate_ai_web.py"
  if errorlevel 1 goto error
  goto done
)

echo Python 3 was not found. Please install Python 3 and try again.
pause
exit /b 1

:error
echo.
echo The modern AI translator could not start. Error code: %errorlevel%
pause
exit /b %errorlevel%

:done
endlocal
