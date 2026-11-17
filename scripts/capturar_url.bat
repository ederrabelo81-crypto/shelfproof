@echo off
REM Shelf Proof - captura uma URL em desktop e mobile, sessao anonima.
REM Uso: scripts\capturar_url.bat https://www.magazineluiza.com.br/
setlocal
cd /d "%~dp0.."
call scripts\_python.bat
set RAC_LOCAL_CHROME=1
if "%RAC_CDP_PORT%"=="" set RAC_CDP_PORT=9223
%PY% -m shelfproof capture %1 --device both
endlocal
