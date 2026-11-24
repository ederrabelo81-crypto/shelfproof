"""Site estatico dos Showrooms (Vercel)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from shelfproof.render.site import add_showroom

REF = Path(__file__).resolve().parents[1] / "reference" / "showroom_2026-11-11"


def test_publica_showroom_e_monta_indice(tmp_path: Path):
    sr = tmp_path / "sr"
    shutil.copytree(REF, sr)
    (sr / "contact_sheet.jpg").write_bytes(b"x")
    site = tmp_path / "site"
    dest = add_showroom(sr, site, "2026-11-11")
    assert (dest / "index.html").exists() and (dest / "img").is_dir()
    assert not (dest / "contact_sheet.jpg").exists()  # folha de revisao nao vai para o ar
    idx = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="2026-11-11/"' in idx and "11.11" in idx and "espaços pagos" in idx
    assert 'http-equiv="refresh" content="0; url=2026-11-11/"' in idx  # home abre o dia mais recente
    assert 'href="../2026-11-11/"' in (site / "dias" / "index.html").read_text(encoding="utf-8")
    ev = json.loads((site / "events.json").read_text(encoding="utf-8"))
    assert ev[0]["slug"] == "2026-11-11" and ev[0]["date"] == "11/11/2026"
    # pagina do dia refeita com o template atual: tem o seletor de dia
    assert 'id="daySel"' in (dest / "index.html").read_text(encoding="utf-8")
    vj = json.loads((site / "vercel.json").read_text())
    assert vj["cleanUrls"] is True and vj["trailingSlash"] is True  # caminhos relativos do Showroom
    # republicar o mesmo slug substitui, nao duplica
    add_showroom(sr, site, "2026-11-11")
    assert (site / "index.html").read_text(encoding="utf-8").count('class="ev"') == 1


def test_slug_invalido(tmp_path: Path):
    with pytest.raises(ValueError):
        add_showroom(REF, tmp_path / "site", "Black Friday!")


def test_especialistas_no_mesmo_dia_ao_lado_dos_marketplaces(tmp_path: Path):
    """24/11/2026: o Showroom dos especialistas (sem pago, com marca em destaque) vai para
    <dia>-especialistas; a home continua abrindo o dos marketplaces e o indice mostra os destaques."""
    mk = tmp_path / "mk"
    shutil.copytree(REF, mk)
    d = json.loads((mk / "data.json").read_text(encoding="utf-8"))
    d["data"]["date"] = "27/11/2026"
    (mk / "data.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    esp = tmp_path / "esp"
    shutil.copytree(REF, esp)
    e = json.loads((esp / "data.json").read_text(encoding="utf-8"))
    e["data"]["date"] = "27/11/2026"
    e["context"]["event_label"] = "Black Friday - Especialistas"
    e["data"]["extras"] = []
    for i, r in enumerate(e["data"]["pieces"]):
        r["k"] = "own"
        if i < 5:
            r["fb"] = "Midea" if i < 3 else "LG"
    (esp / "data.json").write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    site = tmp_path / "site"
    add_showroom(esp, site, "2026-11-27-especialistas")
    add_showroom(mk, site, "2026-11-27")
    ev = json.loads((site / "events.json").read_text(encoding="utf-8"))
    assert [x["slug"] for x in ev] == ["2026-11-27", "2026-11-27-especialistas"]
    assert ev[1]["paid"] == 0 and ev[1]["featured"] == 5
    idx = (site / "index.html").read_text(encoding="utf-8")
    assert 'url=2026-11-27/"' in idx
    assert "banners com marca em destaque" in idx and "em destaque: Midea 3 · LG 2" in idx
