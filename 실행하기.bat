@echo off
chcp 65001 >nul
cd /d "%~dp0"
title MEET PICK
if "%MEETPICK_PORT%"=="" set MEETPICK_PORT=5173

rem ---- 1. Python 찾기 ----
set "PY="
where python >nul 2>nul
if not errorlevel 1 set "PY=python"
if "%PY%"=="" where py >nul 2>nul
if "%PY%"=="" if not errorlevel 1 set "PY=py -3"
if "%PY%"=="" goto no_python

rem ---- 2. 키 파일(.env) 준비 ----
if exist ".env" goto have_env
copy ".env.example" ".env" >nul
echo.
echo  [처음 한 번] 키 파일(.env)을 만들었어요.
echo  메모장이 열리면 받은 키를 "=" 뒤에 붙여넣고 저장한 뒤, 이 창으로 돌아와 아무 키나 누르세요.
echo  (키를 안 채워도 켜지긴 하지만 출발지 검색, 지도, 경로가 동작하지 않아요)
notepad ".env"
pause
:have_env

rem ---- 3. 필요한 프로그램 설치 (처음 한 번만, 1~3분) ----
if exist ".venv\Scripts\python.exe" goto have_venv
echo.
echo  [처음 한 번] 필요한 프로그램을 설치하고 있어요. 1~4분 걸려요. (인터넷 필요)
echo  창을 닫지 말고 기다려 주세요. 끝나면 브라우저가 저절로 열려요.
%PY% -m venv .venv
if errorlevel 1 goto venv_fail
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r backend\requirements.txt
if errorlevel 1 goto pip_fail
:have_venv

rem ---- 4. 실행 ----
echo.
echo  MEET PICK 서버: http://localhost:%MEETPICK_PORT%
echo  잠시 뒤 브라우저가 자동으로 열려요. 이 창을 닫으면 종료돼요.
if "%MEETPICK_NO_BROWSER%"=="" start "" cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:%MEETPICK_PORT%"
cd backend
"..\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port %MEETPICK_PORT%
echo.
echo  서버가 종료됐어요. 위의 오류 메시지를 확인해 주세요. (포트 %MEETPICK_PORT%를 다른 프로그램이 쓰고 있으면 켜지지 않아요)
pause
exit /b

:no_python
echo.
echo  Python이 설치되어 있지 않아요.
echo  https://www.python.org/downloads/ 에서 설치하세요. (설치 첫 화면의 "Add python.exe to PATH"를 꼭 체크)
echo  설치 후 이 파일을 다시 실행하세요.
pause
exit /b 1

:venv_fail
echo.
echo  가상환경을 만들지 못했어요. Python 3.11 이상인지 확인해 주세요.
pause
exit /b 1

:pip_fail
echo.
echo  프로그램 설치에 실패했어요. 인터넷 연결을 확인하고 다시 실행하세요. (".venv" 폴더를 지우고 다시 하면 처음부터 설치해요)
rmdir /s /q .venv >nul 2>nul
pause
exit /b 1
