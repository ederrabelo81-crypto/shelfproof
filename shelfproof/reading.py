"""Leitura da pagina como um cliente: todo criativo que aparece, nao so o que uma regra conhece.

As regras de ``detect/rules.py`` sabem onde cada marketplace marca o espaco vendido (slot da Magalu,
vtr_name da Casas Bahia...). Mas a home tem mais: pop-up de cupom, banner no meio da pagina, lateral
vertical, barra fixa, video, iframe de rede de anuncio. Em 25/11/2026 o Showroom listava marcas em
destaque cujas pecas nao apareciam, porque estavam fora dos carrosseis que as regras leem.

Aqui, a partir do inventario que a captura grava (``creatives.json`` + ``popups/``), o que nenhuma
regra cobriu vira peca, com a ZONA em que apareceu:

    pop-up · barra fixa · lateral · faixa larga · topo (1a tela) · meio da pagina · rodape

Regras duras continuam valendo:
  * pago SO com marcador concreto: iframe de rede de anuncio (doubleclick, criteo...), slot GPT
    (``div-gpt-ad``) ou rotulo "Patrocinado/Publicidade" junto da peca. O resto e da propria loja;
  * marca em destaque so pelo destino, texto ou nome do arquivo (ou pela leitura visual, depois);
  * card de produto (imagem com preco ao lado) nao e criativo: e vitrine.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from urllib.parse import unquote

from shelfproof.detect.rules import (_PRODUCT_HREF, _PRODUCT_SRC, BRAND_STORES, MARKETPLACE_NAMES, SPECIALISTS,
                                     creative_brand)
from shelfproof.models import UNKNOWN_ADVERTISER, BBox, Piece

FOUND_BY = "leitura_da_pagina"
ZONE_POPUP = "pop-up"


def _load(p: Path, default: Any) -> Any:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _iou(a: BBox, b: BBox) -> float:
    x1, y1 = max(a.x, b.x), max(a.y, b.y)
    x2, y2 = min(a.x + a.w, b.x + b.w), min(a.y + a.h, b.y + b.h)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    small = min(a.area, b.area) or 1.0
    return inter / small  # sobreposicao relativa a menor caixa: recorte dentro de banner ja visto


def zone_of(c: Dict[str, Any], vw: float, vh: float) -> str:
    """Onde o cliente ve a peca. ``x``/``y`` na pagina inteira (fixo: na tela)."""
    x, y, w, h = c["x"], c["y"], c["w"], c["h"]
    if c.get("fixed") == "fixed":
        if h >= 1.5 * w and (x + w <= 0.3 * vw or x >= 0.7 * vw):
            return "lateral fixa"
        return "barra fixa"
    if x >= vw - 2 or x + w <= 2:
        return "carrossel"  # slide fora da tela, a direita/esquerda do que esta visivel
    if h >= 1.5 * w and (x + w <= 0.3 * vw or x >= 0.7 * vw):
        return "lateral"
    if y < vh:
        return "topo"
    if w >= 0.8 * vw and h <= 0.35 * w:
        return "faixa larga"
    return "meio da pagina"


def _is_creative(c: Dict[str, Any], vw: float, vh: float, host: str) -> bool:
    if c.get("hidden") or c.get("in_card") or c.get("in_popup") or c.get("kind") == "canvas":
        return False
    w, h = float(c.get("w", 0)), float(c.get("h", 0))
    ad = bool(c.get("ad_host") or c.get("ad_id") or c.get("label"))
    if c.get("kind") == "iframe" and not ad:
        return False  # iframe sem marca de anuncio: mapa, video do YouTube, chat, pagamento
    if c.get("kind") != "iframe" and not (c.get("src") or "").startswith("http"):
        return False
    # card de produto pelo link/imagem (Clima Rio: o preco fica longe da imagem no DOM)
    if _PRODUCT_HREF.search(c.get("href") or "") or _PRODUCT_SRC.search(unquote(c.get("src") or "")):
        return False
    if re.search(r"product|produto|shelf|poly-card|ui-search-result", c.get("ctx") or "", re.I):
        return False
    if re.search(r"\.svg(?:$|\?)|no-image|placeholder|blank\.(?:gif|png)|sprite", c.get("src", ""), re.I):
        return False
    vertical = h >= 250 and w >= 100 and h >= 1.5 * w  # skyscraper 160x600, lateral
    big = w >= max(120.0, 0.15 * vw) and h >= 80 and w * h >= 0.04 * vw * vh
    if not (vertical or big or (ad and w >= 200 and h >= 50)):
        return False
    href = c.get("href") or ""
    p = urlparse(href)
    if c["y"] < 200 and w < 400 and p.path in ("", "/") and p.netloc.endswith(host):
        return False  # logo do proprio site no cabecalho
    return True


def _site_owner(marketplace: str) -> Tuple[str, str]:
    """(ownership, anunciante) de uma peca sem marcador de pago."""
    if marketplace in BRAND_STORES:
        return "brand_store", BRAND_STORES[marketplace]
    return "marketplace", MARKETPLACE_NAMES.get(marketplace, "Site")


def _host_of(marketplace: str, url: str) -> str:
    if marketplace in SPECIALISTS:
        return SPECIALISTS[marketplace][0]
    return urlparse(url).netloc.replace("www.", "")


def read_page(run_dir: Path, pieces: List[Piece], manifest: Dict[str, Any], marketplace: str,
              images: Dict[str, str], src_key: Any) -> List[Piece]:
    """Pecas que so a leitura da pagina viu (nenhuma regra cobriu). Nao altera ``pieces``."""
    run_dir = Path(run_dir)
    data = _load(run_dir / "creatives.json", {})
    items: List[Dict[str, Any]] = data.get("items", []) if isinstance(data, dict) else []
    vp = data.get("viewport") if isinstance(data, dict) else None
    vw = float((vp or manifest.get("viewport") or {}).get("w") or (manifest.get("viewport") or {}).get("width") or 1366)
    vh = float((vp or manifest.get("viewport") or {}).get("h") or (manifest.get("viewport") or {}).get("height") or 768)
    url = manifest.get("final_url") or manifest.get("url", "")
    host = _host_of(marketplace, url)
    own, site = _site_owner(marketplace)

    covered_keys = {src_key(p.img_src) for p in pieces if p.img_src}
    for p in pieces:  # <picture>: a regra guarda a fonte de desktop/celular (Leveros)
        covered_keys |= {src_key(c) for c in p.extra.get("src_candidates", "").split()}
    covered_boxes = [p.bbox for p in pieces if p.bbox is not None]
    img_by_key = {src_key(k): v for k, v in images.items()}
    out: List[Piece] = []
    seen_keys: set = set()

    for c in items:
        if not _is_creative(c, vw, vh, host):
            continue
        key = src_key(c.get("src", "")) if c.get("kind") != "iframe" else f"iframe|{round(c['x'])}|{round(c['y'])}"
        if key and (key in covered_keys or key in seen_keys):
            continue
        box = BBox(c["x"], c["y"], c["w"], c["h"], viewport_h=vh)
        if c.get("fixed") != "fixed" and any(_iou(box, b) > 0.6 for b in covered_boxes):
            continue  # mesma caixa de uma peca que a regra ja leu (imagem em outro tamanho, fundo do banner)
        seen_keys.add(key)
        zone = zone_of(c, vw, vh)
        alt = re.sub(r"\s+", " ", c.get("alt") or "").strip()[:200]
        text = re.sub(r"\s+", " ", c.get("text") or "").strip()[:200]
        evidence = [f"leitura da pagina: {c.get('kind')} {round(c['w'])}x{round(c['h'])} px, zona '{zone}'"]
        extra: Dict[str, str] = {"found_by": FOUND_BY, "zone": zone, "kind": c.get("kind", "")}
        if c.get("fixed"):
            extra["fixed"] = c["fixed"]
        paid_marker = ""
        if c.get("ad_host"):
            paid_marker = f"iframe de rede de anuncio ({c['ad_host']})"
        elif c.get("ad_id"):
            paid_marker = f"espaco de anuncio Google Ad Manager ('{c['ad_id']}')"
        elif c.get("label"):
            paid_marker = f"rotulo '{c['label']}' junto da peca"
        if paid_marker:
            ownership, advertiser = "paid", UNKNOWN_ADVERTISER
            evidence.append(paid_marker)
            evidence.append("anunciante nao aparece no HTML: precisa da leitura visual")
            fmt = "display"
        else:
            ownership, advertiser, fmt = own, site, "banner"
            evidence.append("sem rotulo de patrocinio nem marcador de anuncio: espaco da propria loja")
        brand, source, seen = creative_brand(c.get("href") or "", alt or text, c.get("src") or "")
        if ownership == "paid" and brand:
            advertiser = brand
            evidence = [e for e in evidence if "precisa da leitura visual" not in e]
            evidence.append(f"anunciante pelo {source} da peca: {brand}")
        elif brand:
            extra["featured_brand"] = brand
            extra["featured_brand_source"] = source
            evidence.append(f"marca em destaque: {brand} ({source})")
        else:
            extra["featured_brand"] = ""
            if len(seen) > 1:
                extra["brands_seen"] = ", ".join(seen)
        if c.get("kind") == "img" or c.get("kind") == "background":
            f = images.get(c.get("src", "")) or img_by_key.get(src_key(c.get("src", "")))
            if f:
                extra["image_file"] = f
        if "image_file" not in extra:
            # iframe, video, fundo que nao baixou, fixo: o criativo e o recorte do print
            extra["crop_from"] = "viewport_top.jpg" if c.get("fixed") == "fixed" else "full.jpg"
            extra["crop_box"] = json.dumps([c.get("vx", c["x"]) if c.get("fixed") == "fixed" else c["x"],
                                            c.get("vy", c["y"]) if c.get("fixed") == "fixed" else c["y"],
                                            c["w"], c["h"]])
        out.append(Piece(marketplace, ownership, fmt, advertiser, zone, None,
                         title=alt or text or (f"{zone} {brand}" if brand else zone), alt=alt,
                         href=c.get("href") or "", img_src=c.get("src") or "", evidence=evidence,
                         bbox=box, extra=extra))

    # pop-ups fotografados antes de fechar
    for pop in manifest.get("popups") or []:
        if pop.get("consent") or pop.get("utility") or not pop.get("file"):
            continue
        text = re.sub(r"\s+", " ", pop.get("text") or "").strip()
        brand, source, seen = creative_brand(pop.get("href") or "", text, " ".join(pop.get("imgs") or []))
        extra = {"found_by": FOUND_BY, "zone": ZONE_POPUP, "kind": "popup", "image_file": "",
                 "popup_file": pop["file"], "popup_moment": pop.get("moment", ""),
                 "featured_brand": brand}
        if pop.get("closed"):
            extra["popup_closed"] = "1"
        evidence = [f"janela por cima da pagina ({pop.get('moment', '')}), fotografada antes de fechar",
                    "sem rotulo de patrocinio: janela da propria loja"]
        if brand:
            extra["featured_brand_source"] = source
            evidence.append(f"marca em destaque: {brand} ({source})")
        elif len(seen) > 1:
            extra["brands_seen"] = ", ".join(seen)
        out.append(Piece(marketplace, own, "banner", site, ZONE_POPUP, None, title=text[:160] or "pop-up",
                         href=pop.get("href") or "", img_src="", evidence=evidence,
                         bbox=BBox(pop["x"], pop["y"], pop["w"], pop["h"], viewport_h=vh), extra=extra))
    return out


def materialize_images(pieces: List[Piece], run_dir: Path, manifest: Dict[str, Any]) -> int:
    """Arquivo de imagem das pecas da leitura sem imagem baixada: pop-up (print) ou recorte do print."""
    run_dir = Path(run_dir)
    todo = [p for p in pieces if p.extra.get("found_by") == FOUND_BY and not p.extra.get("image_file")]
    if not todo:
        return 0
    from PIL import Image

    shots: Dict[str, Optional[Any]] = {}
    vw = float((manifest.get("viewport") or {}).get("width") or 0)
    done = 0
    (run_dir / "images").mkdir(exist_ok=True)
    for i, p in enumerate(todo):
        if p.extra.get("popup_file"):
            src = run_dir / p.extra["popup_file"]
            if src.exists():
                import shutil

                fname = f"popup_{i:03d}.jpg"
                shutil.copy(src, run_dir / "images" / fname)
                p.extra["image_file"] = fname
                p.extra["image_source"] = "print da janela antes de fechar"
                done += 1
            continue
        name = p.extra.get("crop_from")
        if not name:
            continue
        if name not in shots:
            try:
                shots[name] = Image.open(run_dir / name).convert("RGB")
            except Exception:
                shots[name] = None
        im = shots[name]
        if im is None:
            continue
        x, y, w, h = json.loads(p.extra["crop_box"])
        scale = im.width / (vw or im.width)
        box = (max(0, int(x * scale)), max(0, int(y * scale)),
               min(im.width, int((x + w) * scale)), min(im.height, int((y + h) * scale)))
        if box[2] - box[0] < 60 or box[3] - box[1] < 40:
            continue
        crop = im.crop(box)
        if max(crop.getextrema()[c][1] - crop.getextrema()[c][0] for c in range(3)) < 12:
            continue  # recorte liso (fora do print, ainda carregando): nao e prova
        fname = f"leitura_{i:03d}.jpg"
        crop.save(run_dir / "images" / fname, "JPEG", quality=88)
        p.extra["image_file"] = fname
        p.extra["image_source"] = f"recorte de {name} pela caixa da peca"
        done += 1
    for p in todo:
        p.extra.pop("crop_from", None)
        p.extra.pop("crop_box", None)
    return done
