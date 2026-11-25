@echo off
setlocal
pushd "%~dp0CreatePreview\server" || exit /b 1
pumpkin-create.exe
set "code=%errorlevel%"
popd
if not "%code%"=="0" pause
exit /b %code%
