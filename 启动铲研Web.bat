@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo [JCC] Opening local JinChanChan archive...
echo Local: http://127.0.0.1:8765/
echo Tailscale phone: run "tailscale serve status" for your private HTTPS URL.
echo.
powershell -NoProfile -Command "try { $null = Invoke-WebRequest 'http://127.0.0.1:8765/api/health' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>nul
if errorlevel 1 (
    schtasks /Run /TN "JCC_Archive_Tailscale" >nul 2>nul
    timeout /t 3 /nobreak >nul
)
powershell -NoProfile -Command "try { $null = Invoke-WebRequest 'http://127.0.0.1:8765/api/health' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 (
    start "" "http://127.0.0.1:8765/"
    echo [JCC] Background server is running. Closing this window will not stop it.
    exit /b 0
)
echo [JCC] Background task unavailable. Falling back to foreground server.
where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 web_server.py
) else (
    python web_server.py
)
if errorlevel 1 (
    echo.
    echo Unable to start. Ensure Python 3 is installed and port 8765 is free.
    pause
)
endlocal
