"""Fase 3 (leitura visual) sem rede: um leitor falso no lugar da Claude API.

O que se trava aqui sao as regras, nao o modelo:
  * so peca PAGA e "Nao identificado" vai para a visao;
  * a visao nunca muda ownership nem troca anunciante que o HTML ja deu;
  * sem marca visivel / confianca baixa / nome do proprio marketplace = continua "Nao identificado";
  * toda peca resolvida carrega a evidencia "lido na imagem";
  * a mesma imagem nao e paga duas vezes (vision.json).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import List, Optional

import pytest

from shelfproof.models import UNKNOWN_ADVERTISER, Piece
from shelfproof.pipeline import summarize
from shelfproof.vision.advertiser import VisualReading, accept, resolve_unknown_advertisers
from shelfproof.vision.evaluate import evaluate_reference

REF = Path(__file__).resolve().parents[1] / "reference" / "showroom_2026-11-11"


class FakeReader:
    model = "fake-vision"

    def __init__(self, readings: List[Optional[VisualReading]]):
        self.readings = list(readings)
        self.calls = 0

    def read(self, image_bytes: bytes, media_type: str, context: str) -> Optional[VisualReading]:
        assert image_bytes and media_type.startswith("image/")
        self.calls += 1
        return self.readings.pop(0)


def R(adv: str, conf: str = "alta", visible: bool = True, people: bool = False) -> VisualReading:
    return VisualReading(brand_visible=visible, advertiser=adv, text_seen=f"logo {adv}" if adv else "",
                         confidence=conf, people_present=people)


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    (tmp_path / "images").mkdir()
    for i, src in enumerate(["amazon_01", "amazon_02", "amazon_03", "magalu_06"]):
        shutil.copy(REF / "img" / f"{src}.webp", tmp_path / "images" / f"img{i}.webp")
    return tmp_path


def _paid(i: int, adv: str = UNKNOWN_ADVERTISER, mkt: str = "amazon") -> Piece:
    return Piece(mkt, "paid", "display", adv, f"desktop-wp-{i}", evidence=["data-csa-c-slot-id 'adplacements:x'"],
                 extra={"image_file": f"img{i}.webp"})


def test_resolve_so_pagas_sem_nome_e_grava_evidencia(run_dir):
    pieces = [
        _paid(0),                                          # resolve
        _paid(1, adv="Samsung"),                           # HTML ja disse: nao toca
        Piece("amazon", "marketplace", "banner", "Amazon", "gateway", extra={"image_file": "img2.webp"}),
        _paid(3),                                          # leitura fraca: fica sem nome
    ]
    reader = FakeReader([R("NEUTROGENA", people=True), R("Nivea", conf="baixa")])
    st = resolve_unknown_advertisers(pieces, run_dir, reader)

    assert reader.calls == 2 and st["candidates"] == 2 and st["resolved"] == 1
    assert pieces[0].advertiser == "Neutrogena"  # nome canonico do dicionario de marcas
    assert pieces[0].ownership == "paid" and pieces[0].extra["advertiser_source"] == "vision"
    assert any("lido na imagem" in e for e in pieces[0].evidence)
    assert pieces[0].extra["people_present"] == "sim"
    assert pieces[1].advertiser == "Samsung" and "advertiser_source" not in pieces[1].extra
    assert pieces[2].ownership == "marketplace" and pieces[2].advertiser == "Amazon"
    assert pieces[3].advertiser == UNKNOWN_ADVERTISER
    assert any("sem marca confiavel" in e for e in pieces[3].evidence)
    s = summarize(pieces)
    assert s["paid_identified_by_vision"] == 1 and s["paid_unidentified"] == 1


def test_cache_nao_paga_a_mesma_imagem_duas_vezes(run_dir):
    reader = FakeReader([R("Electrolux")])
    resolve_unknown_advertisers([_paid(0)], run_dir, reader)
    again = [_paid(0)]
    st = resolve_unknown_advertisers(again, run_dir, FakeReader([]))
    assert st["api_calls"] == 0 and st["cached"] == 1 and again[0].advertiser == "Electrolux"
    cache = json.loads((run_dir / "vision.json").read_text(encoding="utf-8"))
    (entry,) = cache.values()
    assert entry["model"] == "fake-vision" and entry["reading"]["advertiser"] == "Electrolux"


def test_erro_da_api_e_imagem_ausente_nao_derrubam_as_outras(run_dir):
    class Flaky(FakeReader):
        def read(self, *a, **k):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("503")
            return R("Midea")

    pieces = [_paid(0), Piece("amazon", "paid", "display", UNKNOWN_ADVERTISER, "x", extra={}), _paid(3)]
    st = resolve_unknown_advertisers(pieces, run_dir, Flaky([]))
    assert st["errors"] == 1 and st["no_image"] == 1 and st["resolved"] == 1
    assert [p.advertiser for p in pieces] == [UNKNOWN_ADVERTISER, UNKNOWN_ADVERTISER, "Midea"]


@pytest.mark.parametrize("reading,mkt,expected", [
    (R("Samsung"), "amazon", "Samsung"),
    (R("Samsung", conf="media"), "amazon", "Samsung"),
    (R("Samsung", conf="baixa"), "amazon", None),
    (R("Samsung", visible=False), "amazon", None),
    (R(""), "amazon", None),
    (R("Mercado Livre"), "mercadolivre", None),   # o marketplace nao e o anunciante
    (R("Amazon"), "amazon", None),
    (R("Marca Nova Ltda"), "shopee", "Marca Nova Ltda"),  # fora do dicionario: mantem o nome lido
])
def test_regra_de_aceite(reading, mkt, expected):
    assert accept(reading, mkt) == expected


def test_eval_de_referencia_conta_certo_errado_e_abstencao():
    data = json.loads((REF / "data.json").read_text(encoding="utf-8"))["data"]
    paid = [p for p in data["pieces"] if p["k"] == "paid" and p.get("img")][:3]

    class Oracle(FakeReader):
        def read(self, *a, **k):
            self.calls += 1
            truth = paid[self.calls - 1]["adv"]
            return [R(truth), R("Marca Errada"), R("", visible=False)][self.calls - 1]

    rep = evaluate_reference(Oracle([]), limit=3)
    assert [r["outcome"] for r in rep["rows"]] == ["certo", "errado", "sem_gabarito"]
    assert (rep["graded"], rep["right"], rep["wrong"]) == (2, 1, 1)
    assert rep["meets_phase3"] is False


def test_claude_vision_monta_o_pedido_e_trata_recusa():
    from types import SimpleNamespace

    from shelfproof.vision.advertiser import ClaudeVision

    sent = {}

    class Msgs:
        def __init__(self, stop):
            self.stop = stop

        def parse(self, **kw):
            sent.update(kw)
            return SimpleNamespace(stop_reason=self.stop, stop_details=None, parsed_output=R("WAP"))

    def client(stop):
        return SimpleNamespace(beta=SimpleNamespace(messages=Msgs(stop)))

    ok = ClaudeVision(client=client("end_turn")).read(b"x", "image/webp", "Marketplace: shopee")
    assert ok.advertiser == "WAP"
    assert sent["model"] == "claude-opus-5-5" and sent["output_format"] is VisualReading
    assert sent["fallbacks"] == "default" and sent["betas"] == ["server-side-fallback-2026-07-01"]
    img, txt = sent["messages"][0]["content"]
    assert img["source"]["media_type"] == "image/webp" and "shopee" in txt["text"]
    assert ClaudeVision(client=client("refusal")).read(b"x", "image/webp", "") is None
