@echo off
REM 스트림덱 등 콘솔을 숨긴 채 실행하는 프로그램용 런처.
REM 새 창을 강제로 띄워 sync.bat을 실행한다.
REM /c를 쓰는 이유: sync.bat이 끝나면 창도 함께 닫히게 하려는 것이다.
REM (/k는 명령이 끝나도 프롬프트를 남긴다. 대기는 sync.bat의 pause가 맡는다.)
start "watchline sync" cmd /c "%~dp0sync.bat"