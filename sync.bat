@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM 기록 파일(kospi.json / stock_tags.json)을 다른 PC와 맞춘다.
REM 작업 시작 전과 끝난 뒤에 한 번씩 실행하면 된다.

where git >nul 2>nul
if errorlevel 1 (
    echo [오류] git을 찾을 수 없습니다.
    pause
    exit /b 1
)

echo [1/3] 원격 변경 내려받는 중...
git pull --rebase
if errorlevel 1 (
    echo.
    echo [중단] pull에 실패했습니다. 충돌을 정리한 뒤 다시 실행하세요.
    pause
    exit /b 1
)

git diff --quiet -- kospi.json stock_tags.json
if not errorlevel 1 (
    echo.
    echo [완료] 올릴 변경이 없습니다. 최신 상태입니다.
    pause
    exit /b 0
)

echo [2/3] 변경 기록하는 중...
for /f "tokens=1-3 delims=-" %%a in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%a-%%b-%%c
git add kospi.json stock_tags.json
git commit -m "data: %TODAY% 기록 갱신"

echo [3/3] 원격에 올리는 중...
git push
if errorlevel 1 (
    echo.
    echo [중단] push에 실패했습니다.
    pause
    exit /b 1
)

echo.
echo [완료] 기록을 올렸습니다.
pause