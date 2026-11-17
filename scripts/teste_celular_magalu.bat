@echo off
REM Shelf Proof - teste A/B do celular na Magalu (17/11/2026).
REM Roda a home da Magalu no celular com 3 jeitos de emular o celular:
REM   full     = UA Android + client hints + idioma (o padrao ate agora: vitrine vazia, CORS)
REM   no_lang  = UA Android + client hints, sem forcar idioma/plataforma (como o DevTools)
REM   viewport = so tela e toque de celular; o navegador continua se apresentando como desktop
REM Saida em runs_teste\ (fora da coleta do dia). Mande os 3 manifest.json e full.jpg.
REM Uso: scripts\teste_celular_magalu.bat
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
call scripts\_python.bat
set RAC_LOCAL_CHROME=1
if "%RAC_CDP_PORT%"=="" set RAC_CDP_PORT=9223
for %%m in (full no_lang viewport) do (
  echo === modo %%m ===
  set SHELFPROOF_MOBILE_EMULATION=%%m
  %PY% -m shelfproof event --only "Magalu" --devices mobile --out runs_teste --event "Teste celular"
)
echo.
echo Pastas: runs_teste\AAAA-MM-DD\magazineluiza-com-br_mobile_anon_warm_*
echo Em cada manifest.json: "emulation" diz o modo; veja "cors_errors" e "page_height".
endlocal
