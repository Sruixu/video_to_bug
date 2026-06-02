@echo off
REM video_to_bug_gui.bat - 启动 GUI 界面
chcp 65001 >nul
cd /d "%~dp0"
python video_to_bug_gui.py
if errorlevel 1 pause
