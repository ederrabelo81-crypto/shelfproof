"""Leitura da pagina como um cliente (25/11/2026): todo criativo visivel vira peca, com a zona.

Casos tirados do ensaio de 25/11 (Mercado Livre, Frigelar, Dufrio, Leveros, Shopee, WebContinental):
cards de streaming no meio da pagina do ML, faixa do app da Frigelar, pop-up de idioma da Shopee
(utilitario, nao e peca), widget de Libras da Dufrio (camada transparente, nao e janela).
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from shelfproof.pipeline import analyze
from shelfproof.reading import zone_of

VW, VH = 1366, 768


def _creative(kind="img", src="https://cdn.loja.com/banner.jpg", x=0, y=1500, w=1200, h=300, **kw):
    d = {"kind": kind, "src": src, "href": "", "alt": "", "text": "", "x": x, "y": y, "w": w, "h": h,
         "vx": x, "vy": y, "fixed": "", "hidden": False, "in_card": False, "label": "", "ad_host": "",
         "ad_id": "", "ctx": "", "in_popup": False}
    d.update(kw)
    return d


def _run(tmp_path: Path, creatives, popups=(), images=None, html="<html><body></body></html>",
         url="https://www.mercadolivre.com.br/") -> Path:
    rd = tmp_path / "run"
    (rd / "images").mkdir(parents=True)
    (rd / "popups").mkdir()
    (rd / "page.html").write_text(html, encoding="utf-8")
    (rd / "creatives.json").write_text(json.dumps({"viewport": {"w": VW, "h": VH}, "scroll": {"x": 0, "y": 0},
                                                   "items": list(creatives)}), encoding="utf-8")
    (rd / "images.json").write_text(json.dumps(images or {}), encoding="utf-8")
    (rd / "manifest.json").write_text(json.dumps({"url": url, "viewport": {"width": VW, "height": VH},
                                                  "popups": list(popups)}), encoding="utf-8")
    full = Image.new("RGB", (VW, 6000), "white")
    d = ImageDraw.Draw(full)
    for i in range(0, VW, 40):
        d.rectangle([i, 0, i + 20, 6000], fill=(30, 90, 200))
    full.save(rd / "full.jpg")
    full.crop((0, 0, VW, VH)).save(rd / "viewport_top.jpg")
    return rd


def test_zonas():
    assert zone_of(_creative(fixed="fixed", x=1206, y=100, w=160, h=600), VW, VH) == "lateral fixa"
    assert zone_of(_creative(fixed="fixed", x=0, y=700, w=1366, h=68), VW, VH) == "barra fixa"
    assert zone_of(_creative(x=1200, y=900, w=160, h=600), VW, VH) == "lateral"
    assert zone_of(_creative(x=0, y=100, w=1366, h=400), VW, VH) == "topo"
    assert zone_of(_creative(x=1366, y=100, w=1366, h=400), VW, VH) == "carrossel"
    assert zone_of(_creative(x=30, y=3000, w=1300, h=180), VW, VH) == "faixa larga"
    assert zone_of(_creative(x=30, y=3000, w=367, h=250), VW, VH) == "meio da pagina"


def test_meio_da_pagina_lateral_e_iframe_de_anuncio_viram_peca(tmp_path):
    (tmp := tmp_path / "img").mkdir()
    Image.new("RGB", (734, 500), (200, 20, 20)).save(tmp / "x.jpg")
    rd = _run(tmp_path, [
        _creative(src="https://http2.mlstatic.com/hbo.jpg", x=30, y=3402, w=367, h=250, alt="HBO Max"),
        _creative(src="https://http2.mlstatic.com/appletv.jpg", x=420, y=3402, w=367, h=250, alt="Apple TV",
                  href="https://www.mercadolivre.com.br/assinaturas/apple-tv"),
        _creative(src="https://cdn.x/lateral.jpg", x=1200, y=900, w=160, h=600, alt="Ofertas Samsung"),
        _creative(kind="iframe", src="https://securepubads.g.doubleclick.net/x", x=100, y=2000, w=970, h=250,
                  ad_host="doubleclick"),
        # fora: card de produto, iframe comum, icone, escondido, dentro de janela
        _creative(src="https://cdn.x/p1.jpg", in_card=True),
        _creative(kind="iframe", src="https://www.youtube.com/embed/x", x=0, y=4000),
        _creative(src="https://cdn.x/icone.png", w=90, h=90),
        _creative(src="https://cdn.x/oculto.jpg", hidden=True),
        _creative(src="https://cdn.x/dentro.jpg", in_popup=True),
        _creative(src="https://cdn.x/prod.jpg", href="https://www.loja.com/ar-split-12000/p"),
    ], images={"https://http2.mlstatic.com/hbo.jpg": "hbo.jpg"})
    Image.new("RGB", (734, 500), (200, 20, 20)).save(rd / "images" / "hbo.jpg")
    ps = [p for p in analyze(rd) if p.extra.get("found_by") == "leitura_da_pagina"]
    by = {p.title: p for p in ps}
    assert set(by) == {"HBO Max", "Apple TV", "Ofertas Samsung", "meio da pagina"}
    assert by["HBO Max"].extra["zone"] == "meio da pagina" and by["HBO Max"].extra["image_file"] == "hbo.jpg"
    assert by["Apple TV"].extra["featured_brand"] == "Apple" and by["Apple TV"].ownership == "marketplace"
    assert by["Ofertas Samsung"].extra["zone"] == "lateral" and by["Ofertas Samsung"].extra["featured_brand"] == "Samsung"
    ad = by["meio da pagina"]
    assert ad.ownership == "paid" and ad.advertiser == "Nao identificado"
    assert any("doubleclick" in e for e in ad.evidence)
    # sem imagem baixada: recorte do print pela caixa
    assert ad.extra["image_file"].startswith("leitura_") and (rd / "images" / ad.extra["image_file"]).exists()
    assert all(p.advertiser == "Mercado Livre" for p in ps if not p.is_paid)
    summary = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
    assert summary["found_by_page_reading"] == 4 and summary["by_zone"]["meio da pagina"] == 3


def test_pop_up_de_campanha_e_peca_idioma_e_cookies_nao(tmp_path):
    pops = [
        {"id": 0, "x": 383, "y": 134, "w": 600, "h": 500, "text": "Black Friday: cupom de 10% em ar-condicionado Midea",
         "imgs": [], "href": "https://www.loja.com/midea", "consent": False, "utility": False,
         "moment": "abertura", "file": "popups/popup_01.jpg", "closed": True},
        {"id": 1, "x": 0, "y": 0, "w": 1366, "h": 768, "text": "Selecione seu idioma Português (BR)",
         "imgs": [], "href": "", "consent": False, "utility": True, "moment": "abertura", "file": "popups/popup_02.jpg"},
        {"id": 2, "x": 0, "y": 618, "w": 1366, "h": 150, "text": "Usamos cookies", "imgs": [], "href": "",
         "consent": True, "utility": False, "moment": "abertura", "file": "popups/popup_03.jpg"},
    ]
    rd = _run(tmp_path, [], popups=pops)
    for i in (1, 2, 3):
        Image.new("RGB", (600, 500), (10, 120, 60)).save(rd / "popups" / f"popup_0{i}.jpg")
    ps = analyze(rd)
    (pop,) = ps
    assert pop.slot == "pop-up" and pop.ownership == "marketplace"
    assert pop.extra["featured_brand"] == "Midea" and pop.extra["popup_closed"] == "1"
    assert (rd / "images" / pop.extra["image_file"]).exists()
    assert json.loads((rd / "summary.json").read_text(encoding="utf-8"))["popups"] == 1


def test_o_que_a_regra_ja_leu_nao_duplica(tmp_path):
    # Magalu: a regra ja le o banner pago pelo alt "slot"; a leitura ve a mesma imagem e nao repete
    html = ('<html><head><title>Magalu</title></head><body>'
            '<a href="https://www.magazineluiza.com.br/selecao/mideanov26/">'
            '<img alt="Abrir oferta patrocinada - slot desk_home_Ads_medium, posicao 3" '
            'src="https://a-static.mlcdn.com.br/banner/midea.jpg"></a></body></html>')
    rd = _run(tmp_path, [_creative(src="https://a-static.mlcdn.com.br/banner/midea.jpg", x=0, y=900, w=1200, h=300,
                                   href="https://www.magazineluiza.com.br/selecao/mideanov26/")],
              html=html, url="https://www.magazineluiza.com.br/")
    (rd / "elements.json").write_text(json.dumps([{"src": "https://a-static.mlcdn.com.br/banner/midea.jpg",
                                                   "href": "", "x": 0, "y": 900, "w": 1200, "h": 300,
                                                   "visible": True}]), encoding="utf-8")
    ps = analyze(rd)
    assert len(ps) == 1 and ps[0].is_paid and ps[0].advertiser == "Midea"
    assert "found_by" not in ps[0].extra


def test_lateral_estreita_vai_para_a_visao(tmp_path):
    from shelfproof.models import BBox, Piece
    from shelfproof.vision.advertiser import is_featured_candidate

    lat = Piece("amazon", "marketplace", "banner", "Amazon", "lateral", bbox=BBox(1200, 900, 160, 600),
                extra={"found_by": "leitura_da_pagina", "featured_brand": ""})
    assert is_featured_candidate(lat)
    tiny = Piece("amazon", "marketplace", "banner", "Amazon", "meio da pagina", bbox=BBox(0, 900, 200, 120),
                 extra={"found_by": "leitura_da_pagina", "featured_brand": ""})
    assert not is_featured_candidate(tiny)
