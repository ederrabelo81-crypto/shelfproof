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
    assert json.loads((site / "vercel.json").read_text())["cleanUrls"] is True
    # republicar o mesmo slug substitui, nao duplica
    add_showroom(sr, site, "2026-11-11")
    assert (site / "index.html").read_text(encoding="utf-8").count('class="ev"') == 1


def test_slug_invalido(tmp_path: Path):
    with pytest.raises(ValueError):
        add_showroom(REF, tmp_path / "site", "Black Friday!")
