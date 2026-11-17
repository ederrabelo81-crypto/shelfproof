@echo off
REM Shelf Proof - rodada de coleta com o nome do evento no Showroom.
REM Uso: scripts\coleta_evento.bat "Black Friday"
REM A data e sempre a de HOJE (a pasta e runs\showroom\AAAA-MM-DD); rode no dia do evento.
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
if "%~1"=="" (
  echo Uso: scripts\coleta_evento.bat "Nome do evento"
  exit /b 1
)
if not "%~2"=="" echo Aviso: a data da coleta e sempre a de hoje; "%~2" foi ignorado.
call scripts\coleta_dia.bat --event "%~1"
endlocal
