@echo off
REM video2bug_gui.bat - 启动 GUI 界面
chcp 65001 >nul
cd /d "%~dp0"
python video2bug_gui.py
if errorlevel 1 pause
