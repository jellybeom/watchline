@echo off
chcp 65001 > nul
cd /d "%~dp0"

REM 기록 파일(kospi.json / stock_tags.json)을 다른 PC와 맞춘다.
REM 작업 시작 전과 끝난 뒤에 한 번씩 실행하면 된다.
REM 순서: 내 변경을 먼저 커밋 → pull(rebase) → push

setlocal enabledelayedexpansion

where git >nul 2>nul
if errorlevel 1 (
    echo [오류] git을 찾을 수 없습니다.
    goto :done
)

git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo [오류] git 저장소가 아닙니다: %cd%
    goto :done
)

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set BRANCH=%%b
echo 브랜치: !BRANCH!
echo 폴더  : %cd%
echo.

REM ── 1. 기록 파일 변경이 있으면 먼저 커밋한다 ──
REM    커밋하지 않은 변경이 남아 있으면 rebase가 거부되므로 순서가 중요하다.
REM    먼저 add해야 새로 생긴 파일(untracked)도 잡힌다.
REM    git diff는 추적 중인 파일만 보므로 add 뒤 --cached로 비교한다.
if exist kospi.json git add kospi.json
if exist stock_tags.json git add stock_tags.json

git diff --cached --quiet -- kospi.json stock_tags.json
if errorlevel 1 (
    echo [1/3] 기록 변경 커밋하는 중...
    for /f "delims=" %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set TODAY=%%d
    git commit -m "data: !TODAY! 기록 갱신"
    if errorlevel 1 (
        echo [중단] commit에 실패했습니다.
        goto :done
    )
) else (
    echo [1/3] 올릴 기록 변경이 없습니다.
)

REM ── 2. 기록 외에 커밋 안 된 변경이 남아 있으면 rebase가 막힌다 ──
REM    작업 트리와 스테이지 양쪽을 본다.
git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
    echo.
    echo [중단] 커밋하지 않은 다른 변경이 있습니다. 아래 파일을 먼저 정리하세요.
    git status --short
    goto :done
)

echo [2/3] 원격 변경 내려받는 중...
git pull --rebase origin !BRANCH!
if errorlevel 1 (
    echo.
    echo [중단] pull에 실패했습니다. 충돌을 정리한 뒤 다시 실행하세요.
    goto :done
)

REM ── 3. 올릴 커밋이 있을 때만 push ──
git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>nul
if errorlevel 1 (
    echo [3/3] 업스트림을 연결하며 올리는 중...
    git push -u origin !BRANCH!
) else (
    git rev-list --count @{u}..HEAD > "%TEMP%\wl_ahead.txt"
    set /p AHEAD=<"%TEMP%\wl_ahead.txt"
    del "%TEMP%\wl_ahead.txt" >nul 2>nul
    if "!AHEAD!"=="0" (
        echo [3/3] 올릴 커밋이 없습니다. 최신 상태입니다.
        goto :ok
    )
    echo [3/3] 원격에 올리는 중... ^(커밋 !AHEAD!개^)
    git push origin !BRANCH!
)
if errorlevel 1 (
    echo.
    echo [중단] push에 실패했습니다.
    goto :done
)

:ok
echo.
echo [완료] 동기화가 끝났습니다.

:done
echo.
pause
endlocal