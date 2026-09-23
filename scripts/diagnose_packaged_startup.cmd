@echo off
setlocal
if "%~1"=="" (
  echo Drag the installed Lumina Studio.exe onto this file.
  echo This opens an isolated test profile and collects startup evidence locally.
  pause
  exit /b 1
)
set "ELECTRON_RUN_AS_NODE=1"
set "NODE_OPTIONS="
set "NODE_PATH="
"%~f1" "%~dp0diagnose_packaged_startup.cjs" "%~f1" "%~dp0report-%RANDOM%-%RANDOM%" "%~dp0node_modules"
pause
