@echo off
rem Windows：双击 start.bat 即可启动工作台
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (
  echo 没找到 Python，请先安装 Python 3.9+：https://www.python.org/downloads/
  pause & exit /b 1
)

echo 检查依赖...
%PY% -c "import openpyxl, PIL" >nul 2>nul
if errorlevel 1 (
  echo 首次运行，正在安装 openpyxl 与 Pillow...
  %PY% -m pip install --quiet -r requirements.txt
)

if not exist config\config.json copy config\config.example.json config\config.json >nul
if not exist demo\catalog.xlsx %PY% demo\generate_demo.py

echo 启动中，浏览器会自动打开 http://127.0.0.1:8765
start "" http://127.0.0.1:8765
%PY% server.py --port 8765
pause
