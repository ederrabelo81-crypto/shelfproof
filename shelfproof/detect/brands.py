"""Dicionario de marcas e extracao de anunciante a partir de texto/URL.

Regra herdada do RAC Position Tracker (config.BRANDS): mais especifico primeiro
("Springer Midea" antes de "Midea"). Aliases cobrem o jeito que os marketplaces
escrevem a marca em slugs de campanha (ex.: Magalu ``/selecao/ssg_te_nov_26``
= Samsung, ``eluxdpznov26`` = Electrolux).
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional, Tuple

# (marca canonica, padroes regex case-insensitive)
BRANDS: List[Tuple[str, List[str]]] = [
    ("Springer Midea", [r"springer\s*midea"]),
    ("Midea", [r"midea"]),
    ("Samsung", [r"samsung", r"\bssg[_\-]", r"galaxy"]),
    ("LG", [r"\blg\b"]),
    ("Apple", [r"\bapple\b", r"iphone", r"\bipad\b", r"macbook"]),
    ("Electrolux", [r"electrolux", r"\belux"]),
    ("Brastemp", [r"brastemp"]),
    ("Consul", [r"\bconsul\b"]),
    ("Philco", [r"philco"]),
    ("Philips", [r"philips"]),
    ("Britânia", [r"brit[aâ]nia"]),
    ("Mondial", [r"mondial"]),
    ("WAP", [r"\bwap\b", r"\bwap[-_]"]),
    ("Gree", [r"\bgree\b"]),
    ("Elgin", [r"elgin"]),
    ("TCL", [r"\btcl\b"]),
    ("Daikin", [r"daikin"]),
    ("Fujitsu", [r"fujitsu"]),
    ("Agratto", [r"agratto"]),
    ("Intel", [r"\bintel\b", r"intel_"]),
    ("Acer", [r"\bacer\b", r"aceraspire", r"acer_"]),
    ("Lenovo", [r"lenovo"]),
    ("Dell", [r"\bdell\b"]),
    ("Motorola", [r"motorola", r"\bmoto\s?g"]),
    # vistos na Magalu em 12/11/2026 (vitrine Patrocinados) e comuns em celular/informatica.
    # Fora de proposito: HP (cavalo-vapor em motor/bomba) e Positivo (palavra comum).
    ("OPPO", [r"\boppo\b"]),
    ("Realme", [r"\brealme\b"]),
    ("Multilaser", [r"multilaser"]),
    ("JBL", [r"\bjbl\b"]),
    ("Asus", [r"\basus\b"]),
    ("Xiaomi", [r"xiaomi", r"redmi"]),
    ("Sony", [r"\bsony\b", r"playstation", r"\bps5\b"]),
    ("Neutrogena", [r"neutrogena"]),
    ("Oster", [r"\boster\b"]),
    ("Gshield", [r"gshield"]),
    ("Havaianas", [r"havaianas"]),
    ("Multimóveis", [r"multim[oó]veis"]),
    ("Bitlar", [r"bitlar"]),
    ("Arno", [r"\barno\b"]),
    ("TESSAN", [r"tessan"]),
    ("Black+Decker", [r"black\s*\+?\s*decker"]),
    ("Nivea", [r"nivea"]),
    ("Cadence", [r"cadence"]),
    ("Tramontina", [r"tramontina"]),
    ("Hisense", [r"hisense"]),
    ("Toshiba", [r"toshiba"]),
    ("Panasonic", [r"panasonic"]),
    ("Haier", [r"haier"]),
]

_COMPILED = [(name, [re.compile(p, re.I) for p in pats]) for name, pats in BRANDS]


def find_brand(*texts: Optional[str]) -> Optional[str]:
    """Primeira marca encontrada, na ordem de prioridade do dicionario."""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    for name, pats in _COMPILED:
        if any(p.search(blob) for p in pats):
            return name
    return None


def find_brand_first(*texts: Optional[str]) -> Optional[str]:
    """Marca que aparece PRIMEIRO no texto (titulo de produto).

    "Notebook Lenovo LOQ ... Intel Core i5" e da Lenovo: o processador vem depois.
    Empate na mesma posicao segue a prioridade do dicionario ("Springer Midea" antes de "Midea").
    """
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    best: Optional[Tuple[int, int, str]] = None
    for rank, (name, pats) in enumerate(_COMPILED):
        for p in pats:
            m = p.search(blob)
            if m and (best is None or (m.start(), rank) < best[:2]):
                best = (m.start(), rank, name)
    return best[2] if best else None


def find_brands(texts: Iterable[str]) -> List[str]:
    """Todas as marcas presentes (sem repeticao, na ordem do dicionario)."""
    blob = " ".join(t for t in texts if t)
    return [name for name, pats in _COMPILED if any(p.search(blob) for p in pats)]
