"""Da captura bruta as pecas classificadas, com caixa na pagina e arquivo da imagem.

    runs/<data>/<captura>/page.html + elements.json + images.json
        -> detect()                     (quem e pago, de quem, qual slot)
        -> casa com elements.json       (onde esta, que area ocupa, qual dobra)
        -> casa com images.json         (qual arquivo e o criativo)
        -> [opcional] leitura visual    (anunciante das pagas "Nao identificado", fase 3)
        -> pieces.json + summary.json
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from shelfproof.detect.rules import detect
from shelfproof.models import UNKNOWN_ADVERTISER, BBox, Piece


def _norm(u: str) -> str:
    return (u or "").split("#")[0].strip()


def _load_json(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def analyze(run_dir: Path, reader: Optional[Any] = None) -> List[Piece]:
    """Classifica a captura. ``reader`` (vision.advertiser.VisionClient) liga a leitura visual."""
    run_dir = Path(run_dir)
    manifest = _load_json(run_dir / "manifest.json", {})
    html = (run_dir / "page.html").read_text(encoding="utf-8", errors="ignore")
    pieces = detect(html, manifest.get("final_url") or manifest.get("url", ""))
    elements: List[Dict[str, Any]] = _load_json(run_dir / "elements.json", [])
    images: Dict[str, str] = _load_json(run_dir / "images.json", {})
    vh = float((manifest.get("viewport") or {}).get("height") or 0)

    by_src: Dict[str, Dict[str, Any]] = {}
    by_href: Dict[str, Dict[str, Any]] = {}
    # slides escondidos do carrossel tambem sao pecas: casa todos, preferindo o visivel
    for e in sorted(elements, key=lambda e: e.get("visible") is False):
        by_src.setdefault(_norm(e.get("src", "")), e)
        if e.get("href"):
            by_href.setdefault(_norm(e["href"]), e)

    for p in pieces:
        el: Optional[Dict[str, Any]] = by_src.get(_norm(p.img_src)) or by_href.get(_norm(p.href))
        if el:
            p.bbox = BBox(el["x"], el["y"], el["w"], el["h"], viewport_h=vh)
            src = _norm(el.get("src", ""))
            if src in images:
                p.extra["image_file"] = images[src]
        if "image_file" not in p.extra and _norm(p.img_src) in images:
            p.extra["image_file"] = images[_norm(p.img_src)]

    # tempo no ar na 1a tela: em quantos frames do carrossel a peca estava visivel
    frames = manifest.get("frames") or []
    if frames:
        for p in pieces:
            srcs = {_norm(p.img_src)}
            if p.bbox is not None:
                el = by_src.get(_norm(p.img_src)) or by_href.get(_norm(p.href))
                if el:
                    srcs.add(_norm(el.get("src", "")))
            hits = sum(1 for f in frames if srcs & {_norm(x) for x in f.get("visible_imgs", [])})
            if hits:
                p.extra["airtime_first_screen"] = f"{hits}/{len(frames)}"

    if reader is not None:
        from shelfproof.vision.advertiser import resolve_unknown_advertisers

        st = resolve_unknown_advertisers(pieces, run_dir, reader)
        logger.info(f"visao: {st['resolved']}/{st['candidates']} anunciantes lidos na imagem "
                    f"({st['api_calls']} chamadas, {st['cached']} do cache, {st['no_image']} sem imagem, "
                    f"{st['errors']} erros)")

    (run_dir / "pieces.json").write_text(
        json.dumps([p.to_dict() for p in pieces], ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(summarize(pieces), ensure_ascii=False, indent=1), encoding="utf-8")
    return pieces


def summarize(pieces: List[Piece]) -> Dict[str, Any]:
    """Contagens e share of pixels por propriedade e por anunciante."""
    count = defaultdict(int)
    area_owner = defaultdict(float)
    paid_by_adv = defaultdict(int)
    area_by_adv = defaultdict(float)
    for p in pieces:
        count[p.ownership] += 1
        a = p.bbox.area if p.bbox else 0.0
        area_owner[p.ownership] += a
        if p.is_paid:
            paid_by_adv[p.advertiser] += 1
            area_by_adv[p.advertiser] += a
    total_area = sum(area_owner.values()) or 1.0
    return {
        "pieces": len(pieces),
        "by_ownership": dict(count),
        "share_of_pixels_by_ownership": {k: round(v / total_area, 4) for k, v in area_owner.items()},
        "paid_by_advertiser": dict(sorted(paid_by_adv.items(), key=lambda kv: -kv[1])),
        "paid_area_by_advertiser": {k: round(v) for k, v in sorted(area_by_adv.items(), key=lambda kv: -kv[1])},
        "paid_unidentified": paid_by_adv.get(UNKNOWN_ADVERTISER, 0),
        "paid_identified_by_vision": sum(1 for p in pieces if p.is_paid and p.extra.get("advertiser_source") == "vision"),
        "first_fold_paid": sum(1 for p in pieces if p.is_paid and p.bbox and p.bbox.fold == 1),
    }
