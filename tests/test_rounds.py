"""Coleta do dia em rodadas + celular no Showroom (17/11/2026)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PIL import Image

from shelfproof.render.showroom import build_from_runs
from shelfproof.rounds import add_round, build_day, day_run_dirs, load_rounds, parse_date

BRT = timezone(timedelta(hours=-3))


def _piece(slot: str, src: str, adv: str = "Samsung", own: str = "paid", y: float = 100, pos: int = 1,
           air: str = "") -> Dict[str, Any]:
    extra = {"image_file": Path(src).name + ".png"}
    if air:
        extra["airtime_first_screen"] = air
    return {"marketplace": "mercadolivre", "ownership": own, "ad_format": "banner", "advertiser": adv,
            "slot": slot, "position": pos, "title": f"peca {src}", "alt": "", "href": "",
            "img_src": f"https://http2.mlstatic.com/{src}.webp", "evidence": ["teste"] if own == "paid" else [],
            "bbox": {"x": 0, "y": y, "w": 800, "h": 300}, "extra": extra}


def _run(root: Path, name: str, device: str, hour: int, pieces: List[Dict[str, Any]]) -> Path:
    rd = root / name
    (rd / "images").mkdir(parents=True)
    for p in pieces:
        Image.new("RGB", (800, 300), (200, 30, 30)).save(rd / "images" / p["extra"]["image_file"])
    man = {"url": "https://www.mercadolivre.com.br/", "marketplace": "mercadolivre", "device": device,
           "session": "anon", "collected_at": datetime(2026, 11, 17, hour, 0, tzinfo=BRT).isoformat()}
    (rd / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    (rd / "pieces.json").write_text(json.dumps(pieces), encoding="utf-8")
    return rd


def _day(tmp_path: Path) -> List[Path]:
    r1 = _run(tmp_path, "r1d", "desktop", 9, [
        _piece("MS_ADS_A", "a", y=100, air="3/8"), _piece("MS_HOME", "b", adv="Mercado Livre", own="marketplace", y=50)])
    r2 = _run(tmp_path, "r2d", "desktop", 10, [
        _piece("MS_ADS_A", "a", y=400, pos=3, air="2/8"), _piece("MS_ADS_C", "c", adv="LG", y=10)])
    m1 = _run(tmp_path, "r1m", "mobile", 9, [_piece("MOB_ADS_A", "a", y=10)])
    return [r1, r2, m1]


def test_mesma_peca_em_duas_rodadas_vira_uma_com_tempo_no_ar(tmp_path):
    out = tmp_path / "sr"
    build_from_runs(_day(tmp_path), out, "Vitrine do dia", "17/11/2026")
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))["data"]
    desk = [p for p in data["pieces"] if p["d"] == "desktop"]
    assert len(desk) == 3  # a, b, c: "a" nas duas rodadas conta uma vez, mesmo trocando de posicao
    a = next(p for p in desk if p["slot"] == "MS_ADS_A")
    assert (a["seen"], a["of"], a["t0"], a["t1"], a["air"]) == (2, 2, "09:00", "10:00", "5/16")
    c = next(p for p in desk if p["slot"] == "MS_ADS_C")
    assert (c["seen"], c["of"]) == (1, 2)
    # ordem estavel: a rodada 1 primeiro (de cima para baixo), a peca nova da rodada 2 depois
    assert [p["img"] for p in desk] == ["ml_01", "ml_02", "ml_03"]
    assert [p["slot"] for p in desk] == ["MS_HOME", "MS_ADS_A", "MS_ADS_C"]
    mob = [p for p in data["pieces"] if p["d"] == "mobile"]
    assert [p["img"] for p in mob] == ["ml_m_01"] and mob[0]["of"] == 1
    assert data["devices"] == ["desktop", "mobile"]
    assert data["rounds"] == {"ml": {"desktop": 2, "mobile": 1}}
    ctx = json.loads((out / "data.json").read_text(encoding="utf-8"))["context"]
    assert "DESKTOP + MOBILE" in ctx["header_line"] and "2 RODADAS" in ctx["header_line"]
    assert any("amostragem" in n for n in ctx["method_notes"])


def test_mesmo_criativo_duas_vezes_na_mesma_captura_sao_duas_posicoes(tmp_path):
    rd = _run(tmp_path, "r", "desktop", 9, [_piece("VITRINE", "x", y=10, pos=1), _piece("VITRINE", "x", y=900, pos=2)])
    out = tmp_path / "sr"
    build_from_runs([rd], out, "E", "17/11/2026")
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))["data"]
    assert len(data["pieces"]) == 2  # S4: produto patrocinado repetido nao e clone


def test_review_exclui_peca_do_celular_e_mantem_no_ranking(tmp_path):
    out = tmp_path / "sr"
    build_from_runs(_day(tmp_path), out, "E", "17/11/2026", review={"exclude": ["ml_m_01"]})
    data = json.loads((out / "data.json").read_text(encoding="utf-8"))["data"]
    assert not any(p["img"] == "ml_m_01" for p in data["pieces"])
    assert any(x["d"] == "mobile" and x["slot"] == "MOB_ADS_A" for x in data["extras"])
    assert not (out / "img" / "ml_m_01.webp").exists()


def test_rodadas_do_dia_somam_e_refazem_o_showroom(tmp_path):
    runs = _day(tmp_path)
    sdir = tmp_path / "showroom" / "2026-11-17"
    t = datetime(2026, 11, 17, 9, tzinfo=BRT)
    add_round(sdir, t, [{"site": "Mercado Livre", "device": "desktop", "ok": True, "run_dir": str(runs[0])},
                        {"site": "Mercado Livre", "device": "mobile", "ok": True, "run_dir": str(runs[2])},
                        {"site": "Magalu", "device": "mobile", "ok": False, "blocked": True,
                         "run_dir": str(tmp_path / "nada")}], "Black Friday")
    assert add_round(sdir, t, [{"site": "Mercado Livre", "device": "desktop", "ok": True,
                                "run_dir": str(runs[1])}]) == 2
    assert len(load_rounds(sdir)) == 2
    assert len(day_run_dirs(sdir)) == 3 and len(day_run_dirs(sdir, ["mobile"])) == 1
    (sdir / "img").mkdir()
    (sdir / "img" / "sobra.webp").write_bytes(b"x")  # montagem anterior nao deixa lixo
    out = build_day(sdir)
    html = out.read_text(encoding="utf-8")
    assert "Black Friday" in html  # o nome do evento vem da 1a rodada
    assert not (sdir / "img" / "sobra.webp").exists()
    data = json.loads((sdir / "data.json").read_text(encoding="utf-8"))
    assert data["data"]["date"] == "17/11/2026"
    assert build_day(tmp_path / "showroom" / "2026-11-18") is None


def test_captura_analisada_depois_entra_no_dia(tmp_path):
    rd = _day(tmp_path)[2]
    pieces = (rd / "pieces.json").read_bytes()
    (rd / "pieces.json").unlink()
    (rd / "page.html").write_text("<html></html>", encoding="utf-8")
    sdir = tmp_path / "showroom" / "2026-11-17"
    add_round(sdir, datetime(2026, 11, 17, 9, tzinfo=BRT), [
        {"site": "Mercado Livre", "device": "mobile", "ok": False, "error": "analise: lxml", "run_dir": str(rd)},
        {"site": "Magalu", "device": "mobile", "ok": False, "blocked": True, "run_dir": str(rd)}])
    assert day_run_dirs(sdir) == []  # ainda sem analise
    (rd / "pieces.json").write_bytes(pieces)  # = python -m shelfproof analyze <rd>
    assert day_run_dirs(sdir) == [rd]  # a bloqueada continua de fora


def test_parse_date():
    assert parse_date("27/11/2026").isoformat() == "2026-11-27"
    assert parse_date("2026-11-27").isoformat() == "2026-11-27"
    with pytest.raises(ValueError):
        parse_date("27-11")


def _browser():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        pytest.skip("sem playwright")
    from shelfproof.browser import playwright_runtime

    pw, _ = playwright_runtime.acquire()
    if pw is None:
        pytest.skip("sem playwright")
    try:  # mesmo navegador dos outros e2e (Chrome comum); sem ele, o Chromium do Playwright
        try:
            return pw, pw.chromium.launch(headless=True, channel="chrome")
        except Exception:
            return pw, pw.chromium.launch(headless=True)
    except Exception as exc:
        playwright_runtime.release()
        pytest.skip(f"sem Chromium: {exc}")


def test_showroom_com_rodadas_e_celular_roda_no_navegador(tmp_path):
    out = tmp_path / "sr"
    html = build_from_runs(_day(tmp_path), out, "Vitrine do dia", "17/11/2026")
    from shelfproof.browser import playwright_runtime

    pw, browser = _browser()
    try:
        page = browser.new_page()
        errors: List[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(html.as_uri())
        page.wait_for_timeout(300)
        assert not errors, errors
        assert page.locator("#devSel").is_visible()
        assert page.locator("#wallGrid .screen").count() == 1
        assert "2/2 rodadas" in page.locator("#wallGrid").inner_text()
        page.click("#devSel .chipbtn[data-dev=mobile]")
        assert page.locator("#wallGrid.mobile").count() == 1
        assert "MOB_ADS_A" in page.locator("#wallGrid").inner_text()
        proof = page.locator("#proofGrid").inner_text()
        assert "No ar" in proof and "09:00–10:00" in proof
        assert "Celular" in page.locator("#ownGrid").inner_text()
        assert not errors, errors
    finally:
        browser.close()
        playwright_runtime.release()


def test_celular_emulado_na_aba_pelo_cdp():
    """anon_warm no celular: a aba de um contexto ja existente vira Android pelo CDP."""
    from shelfproof.browser import playwright_runtime
    from shelfproof.collect.capture import emulate_mobile_tab

    pw, browser = _browser()
    try:
        ctx = browser.new_context()  # como o contexto do perfil: sem opcoes de celular
        page = ctx.new_page()
        cdp = emulate_mobile_tab(page, browser.version)
        page.goto("data:text/html,<meta name=viewport content='width=device-width'><p>x</p>")
        got = page.evaluate("""() => ({ua: navigator.userAgent, w: innerWidth, touch: navigator.maxTouchPoints,
                                       mobile: navigator.userAgentData ? navigator.userAgentData.mobile : null,
                                       platform: navigator.userAgentData ? navigator.userAgentData.platform : null})""")
        assert "Android" in got["ua"] and "Mobile" in got["ua"]
        assert re.search(r"Chrome/" + browser.version.split(".")[0], got["ua"])
        assert got["w"] == 412 and got["touch"] == 5
        assert got["mobile"] in (True, None) and got["platform"] in ("Android", None)
        assert cdp is not None
    finally:
        browser.close()
        playwright_runtime.release()


def test_modo_viewport_so_muda_a_tela():
    from shelfproof.browser import playwright_runtime
    from shelfproof.collect.capture import emulate_mobile_tab

    pw, browser = _browser()
    try:
        page = browser.new_context().new_page()
        emulate_mobile_tab(page, browser.version, mode="viewport")
        page.goto("data:text/html,<meta name=viewport content='width=device-width'><p>x</p>")
        got = page.evaluate("() => ({ua: navigator.userAgent, w: innerWidth, touch: navigator.maxTouchPoints})")
        assert "Android" not in got["ua"] and got["w"] == 412 and got["touch"] == 5
    finally:
        browser.close()
        playwright_runtime.release()


def test_showroom_avisa_celular_so_com_tela(tmp_path):
    rd = _day(tmp_path)
    man = json.loads((rd[2] / "manifest.json").read_text(encoding="utf-8"))
    man["emulation"] = "cdp_tab:viewport"
    (rd[2] / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    out = tmp_path / "sr"
    build_from_runs(rd, out, "E", "17/11/2026")
    notes = json.loads((out / "data.json").read_text(encoding="utf-8"))["context"]["method_notes"]
    assert any("Celular em Mercado Livre" in n and "desktop" in n for n in notes)
