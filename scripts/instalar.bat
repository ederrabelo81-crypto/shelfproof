@echo off
REM Shelf Proof - cria o .venv do projeto e instala as dependencias.
REM Rode uma vez (e de novo quando o requirements.txt mudar). Nao mexe no venv do RAC.
REM Precisa de Python 64 bits: no 32 bits o greenlet (do Playwright) nao tem pacote pronto
REM e pede o compilador C++ (17/11/2026: "py -3" pegou um Python 3.14 32 bits).
REM Uso: scripts\instalar.bat
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 else 1)" || (
    echo O .venv atual e de um Python 32 bits: apagando para recriar.
    rmdir /s /q .venv
  )
)
if not exist .venv\Scripts\python.exe call :criar || exit /b 1
.venv\Scripts\python.exe -c "import sys,struct; print('Python', sys.version.split()[0], struct.calcsize('P')*8, 'bits')"
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install --only-binary=greenlet -r requirements.txt || exit /b 1
.venv\Scripts\python.exe -c "import lxml, bs4, PIL, jinja2, loguru, playwright; print('Dependencias OK')" || exit /b 1
echo Pronto. Os scripts\*.bat passam a usar .venv\Scripts\python.exe
endlocal
goto :eof

:criar
for %%v in (3.13-64 3.12-64 3.11-64 3-64) do (
  py -%%v -c "import sys" >nul 2>&1 && (
    echo Criando .venv com o Python %%v
    py -%%v -m venv .venv && exit /b 0
  )
)
python -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 else 1)" >nul 2>&1 && (
  echo Criando .venv com o python do PATH
  python -m venv .venv && exit /b 0
)
echo Nenhum Python 64 bits encontrado. Instale o Python 3.13 64 bits (python.org) e rode de novo.
exit /b 1
