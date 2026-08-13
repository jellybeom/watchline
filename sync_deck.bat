@echo off
REM 스트림덱 등 콘솔을 숨긴 채 실행하는 프로그램용 런처.
REM 새 창을 강제로 띄워 sync.bat을 실행하고 결과를 볼 수 있게 한다.
start "watchline sync" cmd /k "%~dp0sync.bat"