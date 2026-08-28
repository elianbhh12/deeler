@echo off
REM Lanza el dashboard "AID Flujos Dealer". Doble clic para arrancar.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo No se encontro el entorno virtual .venv
    echo Creandolo ahora...
    python -m venv .venv
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
)

REM Siempre sincroniza dependencias (rapido/no-op si ya estan instaladas) -
REM asi un .venv viejo levanta paquetes nuevos agregados a requirements.txt
REM (ej. boto3 para "Subir a AWS") sin tener que borrar y recrear el venv.
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt

".venv\Scripts\python.exe" -m streamlit run app.py
pause
