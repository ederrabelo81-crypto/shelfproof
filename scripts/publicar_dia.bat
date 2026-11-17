@echo off
REM Shelf Proof - publica o Showroom do dia no site (Vercel). Revise a folha de contato antes.
REM Uso: scripts\publicar_dia.bat              (hoje)
REM      scripts\publicar_dia.bat 2026-11-17
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
set DIA=%~1
if "%DIA%"=="" for /f %%d in ('python -m shelfproof today') do set DIA=%%d
if not exist runs\showroom\%DIA%\index.html (
  echo Nao ha Showroom em runs\showroom\%DIA%. Rode antes scripts\coleta_dia.bat
  exit /b 1
)
call scripts\publicar_site.bat runs\showroom\%DIA% %DIA%
endlocal
