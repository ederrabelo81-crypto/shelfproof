"""Da captura bruta as pecas classificadas, com caixa na pagina e arquivo da imagem.

    runs/<data>/<captura>/page.html + elements.json + images.json
        -> detect()                     (quem e pago, de quem, qual slot)
        -> casa com elements.json       (onde esta, que area ocupa, qual dobra)
        -> casa com images.json         (qual arquivo e o criativo)
        -> [opcional] leitura visual    (anunciante das pagas "Nao identificado", fase 3)
        -> pieces.json + summary.json
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from urllib.parse import parse_qs, urljoin, urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from shelfproof.detect.rules import detect
from shelfproof.models import UNKNOWN_ADVERTISER, BBox, Piece


def _norm(u: str) -> str:
    return (u or "").split("#")[0].strip()


def _src_key(u: str) -> str:
    """Imagem sem o sufixo de tamanho: a Shopee serve '<arquivo>@resize_w797_nl.webp' no navegador
    e '<arquivo>' no <img src> (12/11/2026); o ML troca D_NQ_2X por D_NQ."""
    if not u:
        return ""
    p = urlparse(u)
    if p.path.endswith("/_next/image"):
        # Next.js (Poloar 24/11/2026): toda imagem e /_next/image?url=<arquivo>&w=<largura>;
        # o navegador escolhe outra largura do srcset. A peca e o arquivo do parametro url.
        inner = (parse_qs(p.query).get("url") or [""])[0]
        if inner:
            return _src_key(urljoin(f"{p.scheme}://{p.netloc}/", inner))
    # Amazon: /images/I/<id>.<modificadores>.jpg -- o navegador pede outra qualidade/formato
    # (_FMavif_..._QL54_) do mesmo <id> que o HTML traz (_QL80_). 12/11/2026: 19 pecas sem imagem.
    m = re.match(r"(/images/I/[^./]+)\.", p.path)
    if m and "media-amazon" in p.netloc:
        return f"{p.netloc}{m.group(1)}".lower()
    path = re.sub(r"@[^/]*$", "", p.path)
    path = re.sub(r"\.(webp|jpe?g|png|gif|avif)$", "", path, flags=re.I)
    path = path.replace("D_NQ_2X_", "D_NQ_").replace("D_NQ_NP_2X_", "D_NQ_NP_")
    return f"{p.netloc}{path}".lower()


def _path_key(u: str, base: str) -> str:
    """Host + caminho, sem query: casa link relativo do HTML com o absoluto do navegador."""
    if not u:
        return ""
    p = urlparse(urljoin(base or "", u.strip()))
    return f"{p.netloc}{p.path}".rstrip("/").lower() if p.netloc else ""


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

    base = manifest.get("final_url") or manifest.get("url", "")
    by_srckey: Dict[str, Dict[str, Any]] = {}
    for e in sorted(elements, key=lambda e: e.get("visible") is False):
        by_srckey.setdefault(_src_key(e.get("src", "")), e)
    img_by_srckey = {_src_key(k): v for k, v in images.items()}
    by_path: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for e in elements:
        if e.get("href") and e.get("w", 0) >= 60:
            by_path[_path_key(e["href"], base)].append(e)
    used_by_path: set = set()

    for p in pieces:
        if p.extra.get("needs_box"):
            # banner de especialista: so pela imagem. Varios banners levam ao mesmo link (Poloar) e a
            # versao de celular da peca fica no DOM do desktop (display:none): pelo link, viraria duplicata.
            el = None
            for cand in [p.img_src] + p.extra.get("src_candidates", "").split():
                el = by_src.get(_norm(cand)) or by_srckey.get(_src_key(cand))
                if el:
                    break
        else:
            el = by_src.get(_norm(p.img_src)) or by_href.get(_norm(p.href))
        if el is None and p.img_src:
            el = by_srckey.get(_src_key(p.img_src))
        if el is None and not p.img_src and p.href:
            # card de produto sem imagem no HTML (Magalu "Patrocinados", 12/11/2026): link relativo
            # no HTML x absoluto no navegador. Casa pelo caminho, uma vez por elemento.
            for cand in by_path.get(_path_key(p.href, base), []):
                if id(cand) not in used_by_path:
                    used_by_path.add(id(cand))
                    el = cand
                    break
        if el:
            p.bbox = BBox(el["x"], el["y"], el["w"], el["h"], viewport_h=vh)
            src = _norm(el.get("src", ""))
            if src in images:
                p.extra["image_file"] = images[src]
        if "image_file" not in p.extra and _norm(p.img_src) in images:
            p.extra["image_file"] = images[_norm(p.img_src)]
        if "image_file" not in p.extra and p.img_src and _src_key(p.img_src) in img_by_srckey:
            p.extra["image_file"] = img_by_srckey[_src_key(p.img_src)]

    if elements:
        # banner de especialista sem caixa na pagina renderizada = variante do outro dispositivo
        # (display:none) ou slide que nao existe nesta tela: nao foi visto, nao entra
        pieces = [p for p in pieces if not (p.extra.get("needs_box") and p.bbox is None)]
    for p in pieces:
        p.extra.pop("needs_box", None)

    # leitura da pagina como um cliente (25/11/2026): pop-up, meio da pagina, lateral, barra fixa,
    # iframe de anuncio... tudo o que apareceu e nenhuma regra cobriu
    from shelfproof.detect.rules import identify_marketplace
    from shelfproof.reading import materialize_images, read_page

    try:
        mkt = manifest.get("marketplace") or identify_marketplace(html, base)
        extra_pieces = read_page(run_dir, pieces, manifest, mkt, images, _src_key)
        materialize_images(extra_pieces, run_dir, manifest)
        pieces += extra_pieces
    except Exception as exc:  # a leitura nunca derruba as pecas das regras
        logger.warning(f"leitura da pagina: {exc}")
    for p in pieces:
        p.extra.pop("src_candidates", None)

    # espaco pago sem imagem com caixa conhecida (Amazon adplacements em iframe): recorta do print
    _crop_slots(pieces, run_dir, manifest, _load_json(run_dir / "slots.json", []), vh)
    # a mesma peca contada duas vezes (mesmo link, mesma imagem, mesma caixa): fica uma
    pieces = _drop_exact_duplicates(pieces)

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
                    f"({st['needs_review']} para conferir, {st['api_calls']} chamadas, {st['cached']} do cache, {st['no_image']} sem imagem, "
                    f"{st['errors']} erros)")
        if st["featured_candidates"]:
            logger.info(f"visao: {st['featured_resolved']}/{st['featured_candidates']} banners da loja com "
                        f"marca em destaque lida na imagem")

    (run_dir / "pieces.json").write_text(
        json.dumps([p.to_dict() for p in pieces], ensure_ascii=False, indent=1), encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(summarize(pieces), ensure_ascii=False, indent=1), encoding="utf-8")
    return pieces


def _crop_slots(pieces: List[Piece], run_dir: Path, manifest: Dict[str, Any], slots: List[Dict[str, Any]],
                vh: float) -> int:
    """Recorta do full.jpg o criativo de cada espaco pago sem imagem cuja caixa a captura gravou.

    Amazon celular 17/11/2026: 4 displays adplacements sem <img> (o anuncio vem num iframe), logo sem
    imagem para o Showroom nem para a leitura visual. O print da pagina mostra o criativo.
    """
    if not slots:
        return 0
    todo = [p for p in pieces if p.is_paid and "image_file" not in p.extra]
    if not todo:
        return 0
    try:
        from PIL import Image, ImageStat

        full = Image.open(run_dir / "full.jpg").convert("RGB")
    except Exception:
        return 0
    vw = float((manifest.get("viewport") or {}).get("width") or 0) or float(full.width)
    scale = full.width / vw
    done = 0
    for p in todo:
        slot = next((s for s in slots if s.get("id") and any(s["id"] in e for e in p.evidence)), None)
        if slot is None:
            continue
        box = (max(0, int(slot["x"] * scale)), max(0, int(slot["y"] * scale)),
               min(full.width, int((slot["x"] + slot["w"]) * scale)), min(full.height, int((slot["y"] + slot["h"]) * scale)))
        if box[2] - box[0] < 60 or box[3] - box[1] < 40:
            continue
        crop = full.crop(box)
        if max(ImageStat.Stat(crop).stddev) < 6:  # caixa vazia (anuncio que nao carregou): nao e criativo
            continue
        name = "crop_" + hashlib.sha1(slot["id"].encode()).hexdigest()[:16] + ".jpg"
        (run_dir / "images").mkdir(exist_ok=True)
        crop.save(run_dir / "images" / name, "JPEG", quality=88)
        p.extra["image_file"] = name
        p.extra["image_source"] = "recorte do print da pagina"
        p.evidence.append("imagem recortada do print da pagina pela caixa do espaco (anuncio em iframe)")
        if p.bbox is None:
            p.bbox = BBox(slot["x"], slot["y"], slot["w"], slot["h"], viewport_h=vh)
        done += 1
    return done


def _drop_exact_duplicates(pieces: List[Piece]) -> List[Piece]:
    """Mesma peca duas vezes na mesma caixa (Amazon celular 17/11/2026: dois cards identicos).
    Duas posicoes diferentes continuam duas pecas (S4): so cai o que tem caixa, link e imagem iguais."""
    seen, out = set(), []
    for p in pieces:
        if p.bbox is not None:
            key = (p.ownership, p.href, p.img_src[:200], round(p.bbox.x), round(p.bbox.y), round(p.bbox.w), round(p.bbox.h))
            if key in seen:
                continue
            seen.add(key)
        out.append(p)
    return out


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
    featured: Dict[str, int] = defaultdict(int)
    featured_area: Dict[str, float] = defaultdict(float)
    featured_fold: Dict[str, int] = defaultdict(int)
    for p in pieces:
        fb = p.extra.get("featured_brand")
        # faixa de logos (navegacao por marca) e icone pequeno nao contam como destaque
        if p.is_paid or not fb or p.extra.get("logo_strip") or (p.bbox and p.bbox.w < 300):
            continue
        featured[fb] += 1
        featured_area[fb] += p.bbox.area if p.bbox else 0.0
        if p.bbox and p.bbox.fold == 1:
            featured_fold[fb] += 1
    zones: Dict[str, int] = defaultdict(int)
    for p in pieces:
        zones[p.extra.get("zone") or "regra do site"] += 1
    total_area = sum(area_owner.values()) or 1.0
    return {
        "pieces": len(pieces),
        "by_ownership": dict(count),
        "share_of_pixels_by_ownership": {k: round(v / total_area, 4) for k, v in area_owner.items()},
        "paid_by_advertiser": dict(sorted(paid_by_adv.items(), key=lambda kv: -kv[1])),
        "paid_area_by_advertiser": {k: round(v) for k, v in sorted(area_by_adv.items(), key=lambda kv: -kv[1])},
        "paid_unidentified": paid_by_adv.get(UNKNOWN_ADVERTISER, 0),
        "paid_identified_by_vision": sum(1 for p in pieces if p.is_paid and p.extra.get("advertiser_source") == "vision"),
        "paid_needs_review": [p.advertiser for p in pieces if p.is_paid and p.extra.get("needs_review")],
        "first_fold_paid": sum(1 for p in pieces if p.is_paid and p.bbox and p.bbox.fold == 1),
        # varejo especialista: banner da varejista com marca em destaque (nao e midia paga)
        "featured_by_brand": dict(sorted(featured.items(), key=lambda kv: -kv[1])),
        "featured_area_by_brand": {k: round(v) for k, v in sorted(featured_area.items(), key=lambda kv: -kv[1])},
        "featured_first_fold": dict(sorted(featured_fold.items(), key=lambda kv: -kv[1])),
        "by_zone": dict(sorted(zones.items(), key=lambda kv: -kv[1])),
        "found_by_page_reading": sum(1 for p in pieces if p.extra.get("found_by") == "leitura_da_pagina"),
        "popups": sum(1 for p in pieces if p.extra.get("zone") == "pop-up"),
        "featured_by_vision": sum(1 for p in pieces if p.extra.get("featured_brand_source") == "visao"),
        "featured_needs_review": [p.extra["featured_brand"] for p in pieces
                                  if not p.is_paid and p.extra.get("featured_brand") and p.extra.get("needs_review")],
    }
