@echo off
REM Shelf Proof - UMA rodada da coleta do dia.
REM Abre todas as homes de config\targets.json em desktop e celular, sem login,
REM classifica e refaz o Showroom do dia em runs\showroom\AAAA-MM-DD.
REM Rodar de novo no mesmo dia = mais uma rodada (o Showroom soma todas e mostra
REM em quantas rodadas cada peca apareceu).
REM
REM Uso:
REM   scripts\coleta_dia.bat
REM   scripts\coleta_dia.bat --event "Black Friday"
REM   scripts\coleta_dia.bat --only "Magalu,Casas Bahia"
REM   scripts\coleta_dia.bat --devices mobile
REM   scripts\coleta_dia.bat --vision          (le o anunciante na imagem; precisa de ANTHROPIC_API_KEY)
REM
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
set RAC_LOCAL_CHROME=1
if "%RAC_CDP_PORT%"=="" set RAC_CDP_PORT=9223
for /f %%d in ('python -m shelfproof today') do set HOJE=%%d
if "%HOJE%"=="" (
  echo Python ou o pacote shelfproof nao respondeu. Rode: pip install -r requirements.txt
  exit /b 1
)
echo === Shelf Proof: rodada da coleta de %HOJE% ===
python -m shelfproof event %*
set RC=%ERRORLEVEL%
if not exist runs\showroom\%HOJE%\index.html (
  echo Nenhuma captura util hoje. Veja logs\coleta_%HOJE%.log
  exit /b 2
)
python -m shelfproof contact-sheet runs\showroom\%HOJE%
echo.
echo Showroom do dia:   runs\showroom\%HOJE%\index.html
echo Folha de contato:  runs\showroom\%HOJE%\contact_sheet.jpg
echo Log:               logs\coleta_%HOJE%.log
if "%RC%"=="1" echo ATENCAO: algum site falhou ou foi bloqueado nesta rodada (veja a lista acima).
echo Pessoa real/celebridade? Liste em runs\showroom\%HOJE%\review.json e rode scripts\remontar_dia.bat
echo Para publicar: scripts\publicar_dia.bat
start "" "runs\showroom\%HOJE%\index.html"
endlocal & exit /b %RC%
