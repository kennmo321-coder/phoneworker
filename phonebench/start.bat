@echo off
rem phonebench launcher - double-click to start the bench
cd /d "%~dp0.."
title phonebench
python -m phonebench --port 8765
if errorlevel 1 pause
