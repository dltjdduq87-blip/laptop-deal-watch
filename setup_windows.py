"""Windows setup without a .bat file (Smart App Control blocks downloaded .bat files).

Run once:  py -3 setup_windows.py
Creates .local-venv, installs Playwright + Chromium, adds a desktop shortcut, then opens the app.
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
VENV = HERE / '.local-venv'
PY = VENV / 'Scripts' / 'python.exe'
PYW = VENV / 'Scripts' / 'pythonw.exe'
SHORTCUT_NAME = '노트북 감시 로그인 준비.lnk'


def run(args):
    print('>', ' '.join(str(a) for a in args), flush=True)
    subprocess.run([str(a) for a in args], check=True, cwd=HERE)


def shortcut():
    script = (
        "$d=[Environment]::GetFolderPath('Desktop');"
        "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d $env:LDW_NAME));"
        "$s.TargetPath=$env:LDW_TARGET;$s.Arguments='local_launcher.py';$s.WorkingDirectory=$env:LDW_DIR;$s.Save()")
    env = dict(os.environ, LDW_NAME=SHORTCUT_NAME, LDW_TARGET=str(PYW), LDW_DIR=str(HERE))
    subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True, env=env)


def main():
    if sys.platform != 'win32':
        print('Windows 전용 설치 스크립트입니다.')
        return 1
    if sys.version_info < (3, 10):
        print('Python 3.10 이상이 필요합니다: https://www.python.org/downloads/windows/')
        return 1
    try:
        if not PY.exists():
            run([sys.executable, '-m', 'venv', VENV])
        run([PY, '-m', 'pip', 'install', '--disable-pip-version-check', '-r', HERE / 'requirements-local.txt'])
        if subprocess.run([str(PY), 'local_launcher.py', '--doctor'], cwd=HERE).returncode != 0:
            run([PY, '-m', 'playwright', 'install', 'chromium'])
        shortcut()
        print('설치 완료 · 바탕화면 "노트북 감시 로그인 준비" 바로가기로 실행하세요.')
        subprocess.Popen([str(PYW), 'local_launcher.py'], cwd=HERE)
        return 0
    except subprocess.CalledProcessError as e:
        print('설치 중 오류가 났습니다. 이 창의 내용을 보내주세요 (비밀번호는 보내지 마세요).', e)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
