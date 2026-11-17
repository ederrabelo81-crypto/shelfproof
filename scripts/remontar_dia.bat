@echo off
REM Shelf Proof - refaz o Showroom do dia SEM capturar (ex.: depois de editar o review.json).
REM Uso: scripts\remontar_dia.bat              (hoje)
REM      scripts\remontar_dia.bat 2026-11-17
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
set DIA=%~1
if "%DIA%"=="" for /f %%d in ('python -m shelfproof today') do set DIA=%%d
python -m shelfproof event --rebuild --date %DIA% || exit /b 1
python -m shelfproof contact-sheet runs\showroom\%DIA%
echo Showroom: runs\showroom\%DIA%\index.html
start "" "runs\showroom\%DIA%\index.html"
endlocal
