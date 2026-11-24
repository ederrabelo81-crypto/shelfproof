"""Varejo especialista em ar-condicionado: homes renderizadas em 24/11/2026 (Black Friday).

As fixtures sao as 11 homes abertas num Chromium headless (desktop 1366x768, anonimo), com
scripts e estilos removidos. Os numeros foram conferidos pela lista de banners de cada home
(texto alternativo + destino do clique + arquivo da peca). Se uma regra mudar e um teste quebrar,
confira o banner antes de "corrigir" o teste (regra dura 12).

Nenhuma das 11 marca espaco vendido a marca na home: zero pecas pagas. Banner de marca e banner
da propria loja com a marca em destaque (extra.featured_brand), nunca "paid" (regra dura 1).
"""
from __future__ import annotations

import collections
import gzip
import json
from pathlib import Path

import pytest

from shelfproof.detect.rules import SPECIALISTS, _specialist_brand, detect, identify_marketplace

FIX = Path(__file__).parent / "fixtures" / "homes_2026-11-24"

# site -> (pecas, faixa de logos, marcas em destaque fora da faixa de logos)
EXPECTED = {
    "friopecas": (27, 0, {"Brastemp": 1, "Consul": 1, "Elgin": 1, "Gree": 1, "Hisense": 1, "LG": 1, "Midea": 1,
                          "Philco": 1, "Samsung": 1, "TCL": 1}),
    # Frigelar: carrossel sem link (marca no alt) + mosaico Elgin/Gree
    "frigelar": (36, 0, {"Electrolux": 1, "Elgin": 1, "Gree": 1, "LG": 1, "Midea": 1, "Philco": 1, "Samsung": 1,
                         "TCL": 1}),
    "webcontinental": (32, 24, {"LG": 4, "Philco": 1}),
    "dufrio": (44, 17, {"Midea": 1, "TCL": 1}),
    # Poloar e Denteck: o DOM traz a versao desktop E a de celular de cada slide (x2); quem nao aparece
    # na tela sai no pipeline (sem caixa em elements.json)
    "poloar": (30, 0, {"Daikin": 2, "Fujitsu": 2, "Gree": 2, "LG": 1, "Midea": 2}),
    "climario": (21, 0, {"Aufit": 2, "Hisense": 1, "LG": 2, "Midea": 2, "TCL": 1}),
    "centralar": (7, 0, {"Electrolux": 1, "Elgin": 1, "Samsung": 1, "TCL": 1}),
    "denteck": (23, 0, {"Midea": 2, "Philco": 2, "TCL": 2}),
    "arcerto": (15, 0, {"Elgin": 2, "LG": 2, "Midea": 1, "Samsung": 2, "TCL": 2}),
    "leveros": (37, 14, {"Daikin": 1, "LG": 1}),
    "refricril": (22, 8, {"Agratto": 1, "Elgin": 1, "Gree": 1}),
}


def _load(name: str) -> str:
    return gzip.open(FIX / f"{name}.html.gz", "rt", encoding="utf-8", errors="ignore").read()


@pytest.fixture(scope="module")
def pieces():
    return {name: detect(_load(name)) for name in SPECIALISTS}


def test_as_onze_homes_tem_fixture():
    assert set(EXPECTED) == set(SPECIALISTS)
    targets = json.loads((Path(__file__).resolve().parents[1] / "config" / "targets_especialistas.json")
                         .read_text(encoding="utf-8"))["targets"]
    assert len(targets) == 11
    assert {identify_marketplace("", t["url"]) for t in targets} == set(SPECIALISTS)


@pytest.mark.parametrize("name", sorted(SPECIALISTS))
def test_identifica_o_especialista_pela_pagina_salva(name):
    # a home cita "Midea" logo no comeco: nao pode virar a loja da marca
    assert identify_marketplace(_load(name)) == name


@pytest.mark.parametrize("name", sorted(SPECIALISTS))
def test_banners_e_marcas_em_destaque(pieces, name):
    ps = pieces[name]
    n, logos, featured = EXPECTED[name]
    assert len(ps) == n
    assert sum(1 for p in ps if p.extra.get("logo_strip")) == logos
    got = collections.Counter(p.extra["featured_brand"] for p in ps
                              if p.extra.get("featured_brand") and not p.extra.get("logo_strip"))
    assert dict(got) == featured


def test_nenhum_banner_de_especialista_e_pago(pieces):
    for name, ps in pieces.items():
        for p in ps:
            assert p.ownership == "marketplace", (name, p.title)
            assert p.advertiser == SPECIALISTS[name][1]
            assert p.evidence, (name, p.title)
            if p.extra.get("featured_brand"):
                assert any(p.extra["featured_brand"] in e for e in p.evidence)


def test_banner_trade_continua_da_loja(pieces):
    # Dufrio: alt "Banner TCL Trade" e indicio de verba de trade, nao marcador de midia vendida
    tcl = [p for p in pieces["dufrio"] if p.extra.get("trade_hint")]
    assert len(tcl) == 1
    assert tcl[0].ownership == "marketplace" and tcl[0].extra["featured_brand"] == "TCL"
    assert tcl[0].extra["featured_brand_source"] == "destino"  # /ar-condicionado?Marca=TCL


def test_marca_pelo_texto_quando_o_banner_nao_tem_link(pieces):
    # Frigelar: o carrossel principal nao tem <a>; a marca esta no alt
    midea = [p for p in pieces["frigelar"] if p.extra.get("featured_brand") == "Midea"]
    assert midea and midea[0].extra["featured_brand_source"] == "alt" and not midea[0].href


def test_produto_e_blog_nao_viram_banner(pieces):
    for name, ps in pieces.items():
        for p in ps:
            assert "/upload/produto/" not in p.img_src and "/arquivos/ids/" not in p.img_src, (name, p.img_src)
            assert "/blog/" not in p.href, (name, p.href)


def test_links_e_imagens_absolutos(pieces):
    # o navegador grava links absolutos em elements.json; o casamento depende disso
    for name, ps in pieces.items():
        for p in ps:
            assert not p.href or p.href.startswith("http"), (name, p.href)
            assert p.img_src.startswith("http"), (name, p.img_src)


@pytest.mark.parametrize("href,alt,src,brand,source", [
    ("https://www.centralar.com.br/marcas/Springer-Midea/c/SPRINGER_MIDEA", "", "x.png", "Springer Midea", "destino"),
    ("/ar-condicionado?Marca=TCL", "Banner TCL Trade", "a.webp", "TCL", "destino"),
    ("", "Ar-Cond. LG - até 20%OFF", "LG_BLACK-NOVEMBER_DESKTOP.jpg", "LG", "alt"),
    ("", "", "/v9/home-v9-m01-bf-v2-cassete-samsung-desktop-1380w.webp", "Samsung", "arquivo"),
    ("/c/cupom-de-desconto/", "", "45a5a6bf9e86.webp", "", ""),
])
def test_marca_em_destaque(href, alt, src, brand, source):
    got, how, _seen = _specialist_brand(href, alt, src)
    assert (got, how) == (brand, source)


def test_varias_marcas_no_mesmo_banner_ficam_sem_destaque():
    got, how, seen = _specialist_brand("", "Ofertas Midea, LG e Samsung", "x.png")
    assert got == "" and how == "alt" and set(seen) == {"Midea", "LG", "Samsung"}


def test_pipeline_descarta_banner_que_nao_apareceu_na_tela(tmp_path):
    """Poloar: o DOM do desktop traz a versao de celular de cada slide (display:none). Sem caixa na
    pagina renderizada, a peca nao foi vista e sai; varios banners com o MESMO link nao se confundem."""
    from shelfproof.pipeline import analyze

    rd = tmp_path / "run"
    rd.mkdir()
    link = "https://www.poloar.com.br/ar-condicionado?category-1=ar-condicionado"
    def nxt(name: str, w: int) -> str:
        return f"/_next/image?url=https%3A%2F%2Fpoloar.vtexassets.com%2Fassets%2F{name}.jpg&amp;w={w}&amp;q=75"
    html = ('<html><head><title>Poloar</title></head><body><div class="heroslider_container">'
            f'<a class="heroslider_fullWidthLink__ev50D" href="{link}"><img alt="Ar Condicionado Midea Inverter" src="{nxt("midea-desk", 3840)}"></a>'
            f'<a class="heroslider_fullWidthLink__ev50D" href="{link}"><img alt="Ar Condicionado Midea Inverter" src="{nxt("midea-mob", 3840)}"></a>'
            f'<a class="heroslider_fullWidthLink__ev50D" href="{link}"><img alt="Ar Condicionado G-top Gree" src="{nxt("gree-desk", 3840)}"></a>'
            '</div></body></html>')
    (rd / "page.html").write_text(html, encoding="utf-8")
    (rd / "manifest.json").write_text(json.dumps({"url": "https://www.poloar.com.br/",
                                                  "viewport": {"width": 1366, "height": 768}}), encoding="utf-8")
    # o navegador escolheu outra largura do srcset (w=1920): mesma peca, pelo parametro url
    els = [{"src": "https://www.poloar.com.br" + nxt("midea-desk", 1920).replace("&amp;", "&"), "href": link,
            "x": 0, "y": 80, "w": 1366, "h": 400, "visible": True},
           {"src": "https://www.poloar.com.br" + nxt("gree-desk", 1920).replace("&amp;", "&"), "href": link,
            "x": 0, "y": 900, "w": 1366, "h": 400, "visible": True}]
    (rd / "elements.json").write_text(json.dumps(els), encoding="utf-8")
    ps = analyze(rd)
    assert [p.extra["featured_brand"] for p in ps] == ["Midea", "Gree"]
    assert all(p.bbox is not None and "needs_box" not in p.extra for p in ps)
    summary = json.loads((rd / "summary.json").read_text(encoding="utf-8"))
    assert summary["featured_by_brand"] == {"Midea": 1, "Gree": 1}
    assert summary["featured_first_fold"] == {"Midea": 1}  # o Gree esta na 2a tela (y 900)
    assert summary["paid_by_advertiser"] == {}


def test_picture_casa_pela_fonte_de_desktop():
    """Leveros: <picture><source media=desktop srcset=A><img src=B (celular)>; o navegador mostra A."""
    html = ('<html><head><title>Leveros</title></head><body><div class="main-banner__image-container">'
            '<a href="/c/melhor-ar-condicionado-daikin"><picture>'
            '<source media="(min-width: 768px)" srcset="https://www.leveros.com.br/upload/banner/desk.webp">'
            '<img alt="Daikin" src="https://www.leveros.com.br/upload/banner/mob.webp"></picture></a></div></body></html>')
    (p,) = detect(html, "https://www.leveros.com.br/")
    assert p.slot == "main-banner__image-container" and p.extra["featured_brand"] == "Daikin"
    assert p.extra["src_candidates"] == "https://www.leveros.com.br/upload/banner/desk.webp"


def test_nome_do_slot_sem_prefixo_do_vtex(pieces):
    slots = {p.slot for p in pieces["climario"]}
    assert "imageElementLink" in slots and not any(s.startswith("vtex-") for s in slots)
