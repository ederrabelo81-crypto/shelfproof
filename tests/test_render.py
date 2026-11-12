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
