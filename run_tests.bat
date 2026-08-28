@echo off
REM Corre la suite de tests (validaciones TA/AID/UDZ) sin levantar la interfaz.
setlocal
cd /d "%~dp0"
".venv\Scripts\python.exe" -m pytest tests\ -v
pause
