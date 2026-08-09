@echo off
chcp 65001 > nul
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
    echo [오류] uv를 찾을 수 없습니다.
    echo        설치: powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
    pause
    exit /b 1
)

uv run watchline %*
if errorlevel 1 pause