@echo off
cd /d "%~dp0"
if exist "dist\BazaarTracker\BazaarTracker.exe" (
    "dist\BazaarTracker\BazaarTracker.exe"
) else (
    echo dist\BazaarTracker\BazaarTracker.exe introuvable -- lancement depuis le code source a la place.
    py -m tracker.main
)
pause
