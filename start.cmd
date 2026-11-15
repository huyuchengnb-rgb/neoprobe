@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 NeoProbe ...
python -m neoprobe --serve
if errorlevel 1 (
  echo.
  echo 启动失败。请确认已安装 Python 3.10+ 并已加入 PATH。
  pause
)
