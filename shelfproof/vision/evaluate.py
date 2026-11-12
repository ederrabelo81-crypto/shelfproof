"""Mede a leitura visual contra as pecas pagas do 11.11 conferidas a mao.

Gabarito: ``reference/showroom_2026-11-11/data.json``. Para cada peca paga com
imagem e anunciante conhecido, o nome e escondido e a leitura visual tenta
recupera-lo. Peca paga que nem a revisao manual identificou entra como
"sem gabarito" (so registra o que a visao leu).

Criterio da fase 3 (docs/ROADMAP.md): >= 80% resolvidas e nenhuma marca errada.
Errar e pior que se abster: abstencao vira "Nao identificado"; erro vira prova falsa.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from shelfproof.detect.brands import find_brand
from shelfproof.models import Piece
from shelfproof.vision.advertiser import VisionClient, _context, accept, is_known_brand, prepare_image

REF = Path(__file__).resolve().parents[2] / "reference" / "showroom_2026-11-11"
MKT = {"ml": "mercadolivre", "cb": "casasbahia"}
UNKNOWN_LABELS = {"Nao identificado", "Não identificado"}


def _same(a: str, b: str) -> bool:
    return (find_brand(a) or a).casefold() == (find_brand(b) or b).casefold()


def evaluate_reference(reader: VisionClient, ref_dir: Path = REF, limit: int = 0) -> Dict[str, Any]:
    data = json.loads((ref_dir / "data.json").read_text(encoding="utf-8"))["data"]
    paid = [p for p in data["pieces"] if p["k"] == "paid" and p.get("img")]
    if limit:
        paid = paid[:limit]
    rows: List[Dict[str, Any]] = []
    for r in paid:
        piece = Piece(MKT.get(r["m"], r["m"]), "paid", "display", "Nao identificado", r.get("slot", ""),
                      title=r.get("title", ""))
        img, media = prepare_image(ref_dir / "img" / f"{r['img']}.webp")
        reading = reader.read(img, media, _context(piece))
        got = accept(reading, piece.marketplace) if reading else None
        truth = None if r["adv"] in UNKNOWN_LABELS else r["adv"]
        if truth is None:
            outcome = "sem_gabarito"
        elif got is None:
            outcome = "abstencao"
        else:
            outcome = "certo" if _same(got, truth) else "errado"
        rows.append({"img": r["img"], "truth": truth, "got": got, "outcome": outcome,
                     "needs_review": bool(got) and not is_known_brand(got),
                     "confidence": reading.confidence if reading else None,
                     "text_seen": reading.text_seen if reading else None,
                     "people_present": reading.people_present if reading else None})
    graded = [x for x in rows if x["truth"]]
    right = sum(x["outcome"] == "certo" for x in graded)
    wrong = sum(x["outcome"] == "errado" for x in graded)
    return {
        "graded": len(graded),
        "right": right,
        "wrong": wrong,
        "abstained": sum(x["outcome"] == "abstencao" for x in graded),
        "resolved_rate": round(right / len(graded), 3) if graded else None,
        "meets_phase3": bool(graded) and wrong == 0 and right / len(graded) >= 0.8,
        "rows": rows,
    }
