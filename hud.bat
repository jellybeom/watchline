@echo off
chcp 65001 > nul
cd /d "%~dp0"

rem pythonw는 콘솔을 만들지 않는다. 창만 뜨고 검은 창이 남지 않는다.
set "PYW=.venv\Scripts\pythonw.exe"

if not exist "%PYW%" (
    echo [오류] 가상환경을 찾을 수 없습니다: %PYW%
    echo        저장소 폴더에서 uv sync를 먼저 실행하세요.
    pause
    exit /b 1
)

rem start로 넘기고 이 창은 바로 닫는다. HUD는 독립 프로세스로 남는다.
start "3선 간격" "%PYW%" -m watchline.hud_window