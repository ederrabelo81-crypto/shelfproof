"""O template reproduz o Showroom aprovado a partir do data.json de referencia."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from shelfproof.render.showroom import render

REF = Path(__file__).resolve().parents[1] / "reference" / "showroom_2026-11-11"


def test_template_reproduz_referencia(tmp_path):
    d = json.loads((REF / "data.json").read_text(encoding="utf-8"))
    out = tmp_path / "sr"
    shutil.copytree(REF / "img", out / "img")
    html = render(d["context"], d["data"], out).read_text(encoding="utf-8")
    assert "{{" not in html and "{%" not in html
    assert "Quem comprou a vitrine no <em>11.11</em>?" in html
    data = json.loads(re.search(r"const DATA = (\{.*?\});\n", html, re.S).group(1).replace("<\\/", "</"))
    assert len(data["pieces"]) == 58 and len(data["extras"]) == 13
    for p in data["pieces"]:
        assert (out / "img" / f"{p['img']}.webp").exists(), p["img"]


def test_dados_nao_quebram_o_script(tmp_path):
    d = json.loads((REF / "data.json").read_text(encoding="utf-8"))
    d["data"]["pieces"][0]["title"] = "</script><script>alert(1)</script>"
    html = render(d["context"], d["data"], tmp_path).read_text(encoding="utf-8")
    assert "</script><script>alert(1)" not in html


def test_espaco_pago_em_iframe_e_recortado_do_print(tmp_path):
    # Amazon celular 17/11/2026: display adplacements sem <img>; o criativo so existe no print
    import json as _json

    from PIL import Image, ImageDraw

    from shelfproof.pipeline import analyze

    rd = tmp_path / "run"
    rd.mkdir()
    sid = "adplacements:gateway:atf:gateway-mWeb:abc"
    (rd / "page.html").write_text(f'<html><head><title>Amazon.com.br</title></head><body>'
                                  f'<div data-csa-c-slot-id="{sid}"><iframe></iframe></div>'
                                  f'<div data-csa-c-slot-id="adplacements:gateway:grid-9:x"></div></body></html>',
                                  encoding="utf-8")
    (rd / "manifest.json").write_text(_json.dumps({"url": "https://www.amazon.com.br/", "viewport": {"width": 412, "height": 915}}),
                                      encoding="utf-8")
    full = Image.new("RGB", (824, 4000), "white")  # print em 2x
    d = ImageDraw.Draw(full)
    for i in range(0, 300, 20):
        d.rectangle([20 + i, 220, 30 + i, 500], fill=(200, 30, 30))
    full.save(rd / "full.jpg")
    (rd / "slots.json").write_text(_json.dumps([{"id": sid, "x": 0, "y": 100, "w": 412, "h": 160},
                                                {"id": "adplacements:gateway:grid-9:x", "x": 0, "y": 1500, "w": 412, "h": 160}]),
                                   encoding="utf-8")
    ps = [p for p in analyze(rd) if p.ad_format == "display"]
    atf = next(p for p in ps if p.slot == "atf")
    grid = next(p for p in ps if p.slot == "grid-9")
    assert atf.extra["image_source"] == "recorte do print da pagina"
    crop = Image.open(rd / "images" / atf.extra["image_file"])
    assert crop.size == (824, 320) and atf.bbox.y == 100
    assert "image_file" not in grid.extra  # caixa em branco: anuncio que nao carregou nao vira criativo
