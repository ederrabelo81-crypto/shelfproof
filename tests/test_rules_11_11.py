"""Regressao do detector contra as homes salvas em 11/11/2026.

Os numeros aqui foram conferidos peca a peca (imagens + HTML) na analise que
gerou o Showroom de referencia (reference/showroom_2026-11-11). Se uma regra
mudar e um destes testes quebrar, confira a peca antes de "corrigir" o teste.
"""
from __future__ import annotations

import collections
import gzip
from pathlib import Path

import pytest

from shelfproof.detect.rules import detect, identify_marketplace

FIX = Path(__file__).parent / "fixtures" / "homes_2026-11-11"


def _load(name: str) -> str:
    return gzip.open(FIX / f"{name}.html.gz", "rt", encoding="utf-8", errors="ignore").read()


@pytest.fixture(scope="module")
def pieces():
    return {name: detect(_load(name)) for name in
            ["amazon", "mercadolivre", "magalu", "casasbahia", "shopee", "midea"]}


def _paid_by(ps, adv):
    return [p for p in ps if p.is_paid and p.advertiser == adv]


@pytest.mark.parametrize("name", ["amazon", "mercadolivre", "magalu", "casasbahia", "shopee", "midea"])
def test_identifica_marketplace_pela_pagina_salva(name):
    assert identify_marketplace(_load(name)) == name


def test_toda_peca_paga_tem_evidencia(pieces):
    for name, ps in pieces.items():
        for p in ps:
            if p.is_paid:
                assert p.evidence, f"{name}: peca paga sem evidencia: {p.title}"


def test_magalu_midea_no_carrossel_p4(pieces):
    m = _paid_by(pieces["magalu"], "Midea")
    assert len(m) == 1
    assert m[0].slot == "desk_home_Ads_large_carrossel_p4" and m[0].position == 2


def test_magalu_samsung_domina_trio_superior(pieces):
    trio = [p for p in pieces["magalu"] if p.slot.startswith("desk_home_Ads_trio_superior")]
    assert len(trio) == 3 and {p.advertiser for p in trio} == {"Samsung"}


def test_magalu_campanhas_proprias_nao_viram_pagas(pieces):
    own = [p for p in pieces["magalu"] if p.ownership == "marketplace"]
    slugs = " ".join(p.title for p in own)
    for s in ("antecipadasbf26", "montagem_outros", "diadetelefonia", "entregarapida"):
        assert s in slugs


def test_casasbahia_ads_cb(pieces):
    paid = [p for p in pieces["casasbahia"] if p.is_paid]
    assert {p.advertiser for p in paid} == {"Midea", "WAP"}
    assert len(paid) == 2  # o clone do carrossel nao conta duas vezes


def test_amazon_patrocinados(pieces):
    ps = pieces["amazon"]
    sp = [p for p in ps if p.ad_format == "sponsored_product"]
    assert len(sp) == 12  # 16 rotulos "Patrocinado" visiveis = 4 blocos de marca + 12 produtos
    assert len(_paid_by(ps, "Midea")) == 2
    assert len([p for p in ps if p.ad_format == "display"]) == 4
    nivea = [p for p in ps if p.advertiser == "Nivea"]
    assert nivea and nivea[0].ad_format == "sponsored_brand"


def test_amazon_anunciante_desconhecido_nao_e_chutado(pieces):
    unk = [p for p in pieces["amazon"] if p.is_paid and p.advertiser == "Nao identificado"]
    assert unk, "displays sem anunciante no HTML devem ficar Nao identificado"
    for p in unk:
        assert any("visual" in e or "slot-id" in e for e in p.evidence)


def test_mercadolivre_so_ads_e_pago(pieces):
    paid = [p for p in pieces["mercadolivre"] if p.is_paid]
    assert [(p.advertiser, p.slot) for p in paid] == [("Bitlar", "MS_1111_ADS_BITLAR_MA")]


def test_shopee_lojas_e_ads(pieces):
    paid = {p.advertiser for p in pieces["shopee"] if p.is_paid}
    assert {"WAP", "Multimóveis"} <= paid
    assert any("adsTrackingPayload" in e for p in pieces["shopee"] for e in p.evidence)


def test_loja_da_marca_nunca_tem_midia_paga(pieces):
    ps = pieces["midea"]
    assert ps and all(p.ownership == "brand_store" for p in ps)
    assert collections.Counter(p.slot for p in ps)["banner_tv"] >= 8
