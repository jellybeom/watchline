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

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo [오류] git 저장소가 아닙니다: %cd%
    pause
    exit /b 1
)

REM 현재 브랜치 이름
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
echo 브랜치: %BRANCH%

REM 업스트림이 없으면 origin/<브랜치>로 한 번 연결해 둔다.
git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>nul
if errorlevel 1 (
    echo [설정] 업스트림이 없어 origin/%BRANCH%로 연결합니다.
    git branch --set-upstream-to=origin/%BRANCH% %BRANCH% >nul 2>nul
    if errorlevel 1 (
        echo        원격에 브랜치가 없어 push할 때 함께 만듭니다.
        set NEED_UPSTREAM=1
    )
)

echo [1/3] 원격 변경 내려받는 중...
git pull --rebase origin %BRANCH%
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
for /f "delims=" %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
git add kospi.json stock_tags.json
git commit -m "data: %TODAY% 기록 갱신"
if errorlevel 1 (
    echo.
    echo [중단] commit에 실패했습니다.
    pause
    exit /b 1
)

echo [3/3] 원격에 올리는 중...
if defined NEED_UPSTREAM (
    git push -u origin %BRANCH%
) else (
    git push origin %BRANCH%
)
if errorlevel 1 (
    echo.
    echo [중단] push에 실패했습니다.
    pause
    exit /b 1
)

echo.
echo [완료] 기록을 올렸습니다.
pause