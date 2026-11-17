@echo off
REM Shelf Proof - cria o .venv do projeto e instala as dependencias.
REM Rode uma vez (e de novo quando o requirements.txt mudar). Nao mexe no venv do RAC.
REM Uso: scripts\instalar.bat
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
if not exist .venv\Scripts\python.exe (
  echo Criando .venv do Shelf Proof...
  py -3 -m venv .venv 2>nul || python -m venv .venv || exit /b 1
)
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt || exit /b 1
.venv\Scripts\python.exe -c "import lxml, bs4, PIL, jinja2, playwright; print('Dependencias OK')" || exit /b 1
echo Pronto. Os scripts\*.bat passam a usar .venv\Scripts\python.exe
endlocal
