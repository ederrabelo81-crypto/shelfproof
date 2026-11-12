"""Ponta a ponta do robo contra uma home falsa servida localmente.

Nao toca em marketplace real (nuvem/CI = IP de datacenter). Valida o encanamento:
abrir, observar o carrossel, rolar, salvar artefatos, classificar, casar caixa
e imagem e medir o tempo no ar. Pula se nao houver Chrome/Playwright.
"""
from __future__ import annotations

import functools
import http.server
import json
import shutil
import threading
from pathlib import Path

import pytest

MOCK = Path(__file__).parent / "fixtures" / "mock_magalu"


def _has_browser() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    from shelfproof.browser.local_browser import find_chrome_exe

    # no Windows o Chrome nao fica no PATH: find_chrome_exe olha os caminhos de instalacao
    return bool(shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium")
                or find_chrome_exe())


pytestmark = pytest.mark.skipif(not _has_browser(), reason="sem Playwright/Chrome nesta maquina")


@pytest.fixture(scope="module")
def server():
    class Handler(http.server.SimpleHTTPRequestHandler):
        # no Windows o mimetypes le o registro e .webp pode sair como application/octet-stream:
        # o servidor falso precisa dizer o tipo como um CDN de verdade diz
        extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".webp": "image/webp"}

    handler = functools.partial(Handler, directory=str(MOCK))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}/"
    httpd.shutdown()


def test_captura_classifica_e_mede_tempo_no_ar(server, tmp_path):
    from shelfproof.collect.capture import CaptureConfig, capture
    from shelfproof.pipeline import analyze

    res = capture(CaptureConfig(url=server, engine="launch", headless=True, out_root=tmp_path,
                                carousel_seconds=6, carousel_interval=2))
    assert res.ok, res.errors
    for f in ("page.html", "elements.json", "full.jpg", "images.json", "manifest.json"):
        assert (res.run_dir / f).exists(), f
    pieces = analyze(res.run_dir)
    paid = {p.advertiser for p in pieces if p.is_paid}
    assert {"Apple", "Samsung", "Midea", "Intel"} <= paid
    midea = next(p for p in pieces if p.advertiser == "Midea")
    assert midea.bbox is not None and midea.bbox.fold == 1
    assert midea.extra.get("image_file"), (
        "o criativo baixado precisa estar ligado a peca: "
        f"images={json.loads((res.run_dir / 'images.json').read_text(encoding='utf-8'))} errors={res.errors}")
    intel = next(p for p in pieces if p.advertiser == "Intel")
    assert intel.bbox.fold >= 2  # abaixo da dobra
    manifest = json.loads((res.run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert all(len(f["visible_imgs"]) <= 1 for f in manifest["frames"]), "so um slide no ar por vez"
    assert any("airtime_first_screen" in p.extra for p in pieces)
