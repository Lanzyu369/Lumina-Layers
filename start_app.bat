@echo off
chcp 65001 >nul
cd /d "%~dp0electron"
pnpm start
