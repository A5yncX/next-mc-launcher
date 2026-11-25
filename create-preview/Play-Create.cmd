@echo off
setlocal
set "root=%~dp0CreatePreview"
set "resources=%LOCALAPPDATA%\NextMC\resources-create-v4"
if not "%~1"=="" set "resources=%~f1"
if not exist "%resources%\horizon-resources.json" (
    echo Create resources not found: "%resources%"
    echo Prepare Create resources with Next MC beta.2, then run Start-Server.cmd and try again.
    pause
    exit /b 1
)
set "HORIZON_TELEMETRY_URL=off"
pushd "%root%\player" || exit /b 1
"%root%\bin\horizon-client.exe" --name CreatePlayer --resources "%resources%" --game-dir "%root%\player" --home "%root%\player" --quickPlayMultiplayer 127.0.0.1:25586 > client.log 2>&1
set "code=%errorlevel%"
if not "%code%"=="0" (
    echo The game exited with error %code%. See "%root%\player\client.log".
    pause
)
popd
exit /b %code%
