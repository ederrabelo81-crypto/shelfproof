@echo off
REM Shelf Proof - publica no site (Vercel) o Showroom dos especialistas de ar-condicionado.
REM Fica em <dia>-especialistas, ao lado do Showroom dos marketplaces do mesmo dia
REM (o seletor "Dia" no topo de cada Showroom troca entre os dois).
REM Uso: scripts\publicar_especialistas.bat              (hoje)
REM      scripts\publicar_especialistas.bat 2026-11-27
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
call scripts\_python.bat
set DIA=%~1
if "%DIA%"=="" for /f %%d in ('%PY% -m shelfproof today') do set DIA=%%d
if not exist runs\especialistas\showroom\%DIA%\index.html (
  echo Nao ha Showroom em runs\especialistas\showroom\%DIA%. Rode antes scripts\coleta_especialistas.bat
  exit /b 1
)
call scripts\publicar_site.bat runs\especialistas\showroom\%DIA% %DIA%-especialistas
endlocal
