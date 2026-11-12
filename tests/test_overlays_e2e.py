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


HTML_SHOPEE = """<html><body>
<div id="top"><span id="hdr">Português (BR)</span></div>
<div style="height:300px"></div>
<div id="lang" style="position:fixed;top:200px;left:300px;background:#fff">
  <div>Selecione seu idioma</div>
  <div class="opt" onclick="document.getElementById('lang').remove()">Português (BR)</div>
  <div class="opt" onclick="document.body.dataset.en=1">English*</div>
</div>
<script>document.getElementById('hdr').onclick=()=>{document.body.dataset.menu=1}</script>
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


@pytest.mark.skipif(not _has_browser(), reason="sem Playwright/Chrome nesta maquina")
def test_janela_de_idioma_sem_botao_clica_a_opcao_da_janela_e_nao_a_do_cabecalho():
    from shelfproof.browser import playwright_runtime
    from shelfproof.collect.capture import dismiss_overlays

    pw, _ = playwright_runtime.acquire()
    browser = pw.chromium.launch(headless=True, channel="chrome")
    try:
        page = browser.new_page()
        page.set_content(HTML_SHOPEE)
        assert dismiss_overlays(page) == ["Português (BR)"]
        assert page.locator("#lang").count() == 0
        assert page.evaluate("document.body.dataset.menu") is None  # cabecalho intocado
        assert page.evaluate("document.body.dataset.en") is None
        assert dismiss_overlays(page) == []  # sem a janela, o texto do cabecalho nao e clicado
    finally:
        browser.close()
        playwright_runtime.release()


@pytest.mark.skipif(not _has_browser(), reason="sem Playwright/Chrome nesta maquina")
def test_peca_em_fundo_css_entra_nos_elementos():
    # ML 12/11/2026: os cards de iPhone sao <div> com background-image dentro do link, sem <img>
    from shelfproof.browser import playwright_runtime
    from shelfproof.collect.capture import ELEMENTS_JS

    pw, _ = playwright_runtime.acquire()
    browser = pw.chromium.launch(headless=True, channel="chrome")
    try:
        page = browser.new_page()
        page.set_content('<a href="https://lista.mercadolivre.com.br/loja/apple"><div style="width:400px;height:200px;'
                         'background-image:url(https://http2.mlstatic.com/D_NQ_2X_1-MLA1-OO.webp)">IPHONE</div></a>')
        els = page.evaluate(ELEMENTS_JS)
        bg = [e for e in els if e.get("background")]
        assert len(bg) == 1 and bg[0]["src"].endswith("MLA1-OO.webp") and bg[0]["w"] == 400
        assert bg[0]["href"].endswith("/loja/apple")
    finally:
        browser.close()
        playwright_runtime.release()
