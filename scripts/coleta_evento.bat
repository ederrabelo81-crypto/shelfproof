@echo off
REM Shelf Proof - coleta de evento (todas as homes de config\targets.json, desktop + mobile)
REM Uso: scripts\coleta_evento.bat "Black Friday" 27/11/2026
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
if not exist logs mkdir logs
set RAC_LOCAL_CHROME=1
if "%RAC_CDP_PORT%"=="" set RAC_CDP_PORT=9223
if "%~1"=="" (
  echo Uso: scripts\coleta_evento.bat "Nome do evento" DD/MM/AAAA
  exit /b 1
)
python -m shelfproof event --event "%~1" --date %2 >> logs\coleta_evento.log 2>&1
echo Fim. Log em logs\coleta_evento.log
endlocal
