"""Janelas por cima da vitrine (Shopee, 12/11/2026): idioma + aviso de cookies.

O robo clica so em botoes de nome exato (idioma, aceitar cookies) e registra o que clicou.
Pula sem Playwright/Chrome.
"""
from __future__ import annotations

import shutil

import pytest

HTML = """<html><body>
<div id="vitrine"><img src="data:," alt="Lojas Oficiais"></div>
<div id="lang" style="position:fixed;inset:0;background:#fff">
  <p>Selecione seu idioma</p>
  <button onclick="document.getElementById('lang').remove()">Português (BR)</button>
  <button onclick="document.body.dataset.en=1">English*</button>
</div>
<div id="ck" style="position:fixed;bottom:0">Usamos cookies
  <button>Configurações de cookies</button>
  <button onclick="document.getElementById('ck').remove()">Aceitar todos os cookies</button>
</div>
<button id="login">Entrar</button>
</body></html>"""


def _has_browser() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    from shelfproof.browser.local_browser import find_chrome_exe

    return bool(shutil.which("chromium") or shutil.which("google-chrome") or find_chrome_exe())


@pytest.mark.skipif(not _has_browser(), reason="sem Playwright/Chrome nesta maquina")
def test_fecha_idioma_e_cookies_sem_clicar_em_mais_nada():
    from shelfproof.browser import playwright_runtime
    from shelfproof.collect.capture import dismiss_overlays

    pw, _ = playwright_runtime.acquire()
    browser = pw.chromium.launch(headless=True, channel="chrome")  # mesmo navegador do e2e da captura
    try:
        page = browser.new_page()
        page.set_content(HTML)
        clicked = dismiss_overlays(page)
        assert clicked == ["Português (BR)", "Aceitar todos os cookies"]
        assert page.locator("#lang").count() == 0 and page.locator("#ck").count() == 0
        assert page.evaluate("document.body.dataset.en") is None  # nao escolheu ingles
        assert dismiss_overlays(page) == []  # nada mais a fechar
    finally:
        browser.close()
        playwright_runtime.release()
