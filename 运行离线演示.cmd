@echo off
chcp 65001 >nul
cd /d "%~dp0"
python demo
un_demo.py
if errorlevel 1 (echo 演示检查失败，请查看 demo\output
eport.json) else (echo 演示完成，请查看 demo\output
eport.json)
pause
