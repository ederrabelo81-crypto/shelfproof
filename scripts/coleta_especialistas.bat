@echo off
REM Shelf Proof - UMA rodada no varejo especialista em ar-condicionado.
REM Abre as 11 homes de config\targets_especialistas.json (Friopecas, Frigelar,
REM WebContinental, Dufrio, Poloar, Clima Rio, CentralAr, Denteck, ArCerto,
REM Leveros, Refricril) em desktop e celular, sem login, e refaz o Showroom do
REM dia em runs\especialistas\showroom\AAAA-MM-DD (separado dos marketplaces).
REM Rodar de novo no mesmo dia = mais uma rodada.
REM
REM Uso:
REM   scripts\coleta_especialistas.bat
REM   scripts\coleta_especialistas.bat --only "Frigelar,Dufrio"
REM   scripts\coleta_especialistas.bat --devices desktop
REM   scripts\coleta_especialistas.bat --rebuild      (refaz sem capturar, depois do review.json)
REM
REM Leitura visual LIGADA: banner da loja sem marca no link/alt/arquivo tem a marca
REM lida na imagem (precisa de ANTHROPIC_API_KEY no .env; sem a chave, segue sem ler).
REM O banner continua da loja: a leitura nao cria peca paga.
REM
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
call scripts\_python.bat
set RAC_LOCAL_CHROME=1
if "%RAC_CDP_PORT%"=="" set RAC_CDP_PORT=9223
for /f %%d in ('%PY% -m shelfproof today') do set HOJE=%%d
if "%HOJE%"=="" (
  echo Python ou o pacote shelfproof nao respondeu. Rode: scripts\instalar.bat
  exit /b 1
)
set SR=runs\especialistas\showroom\%HOJE%
echo === Shelf Proof: especialistas de ar-condicionado, %HOJE% ===
%PY% -m shelfproof event --targets config\targets_especialistas.json --out runs\especialistas --event "Black Friday - Especialistas" --vision %*
set RC=%ERRORLEVEL%
if not exist %SR%\index.html (
  echo Nenhuma captura util hoje. Veja logs\coleta_%HOJE%.log
  exit /b 2
)
%PY% -m shelfproof contact-sheet %SR%
echo.
echo Showroom do dia:   %SR%\index.html
echo Folha de contato:  %SR%\contact_sheet.jpg
echo Resumo por site:   runs\especialistas\AAAA-MM-DD\*\summary.json (featured_by_brand)
if "%RC%"=="1" echo ATENCAO: algum site falhou ou foi bloqueado nesta rodada (veja a lista acima).
echo Pessoa real/celebridade? Liste em %SR%\review.json e rode este script com --rebuild
start "" "%SR%\index.html"
endlocal & exit /b %RC%
