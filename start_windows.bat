@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 노트북 로그인 준비 프로그램을 시작합니다.
set "TASK_PYTHON="
py -3 -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
if not errorlevel 1 set "TASK_PYTHON=py -3"
if not defined TASK_PYTHON (
 python -c "import sys; sys.exit(sys.version_info < (3,10))" >nul 2>nul
 if not errorlevel 1 set "TASK_PYTHON=python"
)
if not defined TASK_PYTHON (
 echo Python 3.10 이상이 필요합니다. https://www.python.org/downloads/windows/
 echo 설치할 때 Add python.exe to PATH를 선택한 뒤 다시 실행하세요.
 pause
 exit /b 1
)
if not exist ".local-venv\Scripts\python.exe" (
 %TASK_PYTHON% -m venv .local-venv
 if errorlevel 1 goto failed
)
".local-venv\Scripts\python.exe" -c "import importlib.metadata as m; assert m.version('playwright') == '1.64.1'" >nul 2>nul
if errorlevel 1 (
 echo 최초 실행 구성요소 설치 중입니다. 창을 닫지 마세요.
 ".local-venv\Scripts\python.exe" -m pip install -r requirements-local.txt
 if errorlevel 1 goto failed
)
".local-venv\Scripts\python.exe" local_launcher.py --doctor
if errorlevel 1 (
 echo 전용 브라우저를 설치합니다.
 ".local-venv\Scripts\python.exe" -m playwright install chromium
 if errorlevel 1 goto failed
)
".local-venv\Scripts\python.exe" local_launcher.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo 실행하지 못했습니다. 이 창의 오류 화면을 보내주세요. 비밀번호는 보내지 마세요.
pause
exit /b 1
