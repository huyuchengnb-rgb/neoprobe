@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 NeoProbe 窗口...
python -m neoprobe --desktop
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已安装 Python 3.10+ 并已加入 PATH，
  echo 或者直接双击 dist\NeoProbe.exe。
  pause
)
