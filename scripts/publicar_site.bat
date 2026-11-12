@echo off
REM Shelf Proof - publica um Showroom no site (Vercel).
REM Uso: scripts\publicar_site.bat runs\showroom\2026-11-12 2026-11-12
REM 1a vez: a CLI da Vercel pede login no navegador. Precisa de Node.js instalado.
REM ASCII only (ver COMMON_MISTAKES R13).
setlocal
cd /d "%~dp0.."
if "%~2"=="" (
  echo Uso: scripts\publicar_site.bat PASTA_DO_SHOWROOM SLUG
  echo Ex.: scripts\publicar_site.bat runs\showroom\2026-11-12 2026-11-12
  exit /b 1
)
python -m shelfproof site "%~1" --slug %2 || exit /b 1
call npx --yes vercel@latest deploy site --prod --yes --project shelfproof-showroom --create-if-missing
endlocal
