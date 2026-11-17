@echo off
REM Shelf Proof - escolhe o Python do PROPRIO projeto (.venv da pasta shelf-proof).
REM Mesmo com o .venv do RAC ativado no terminal, os scripts usam o do Shelf Proof:
REM o venv do RAC nao tem o lxml (17/11/2026) e as versoes de um nao devem mexer no outro.
REM Chamado pelos outros .bat (call scripts\_python.bat), ja dentro da pasta do projeto.
REM ASCII only (ver COMMON_MISTAKES R13).
if exist .venv\Scripts\python.exe (
  set PY=.venv\Scripts\python.exe
) else (
  set PY=python
  echo AVISO: sem .venv do Shelf Proof; usando o python do PATH. Rode scripts\instalar.bat
)
