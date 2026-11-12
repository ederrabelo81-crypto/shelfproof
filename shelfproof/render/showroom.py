"""Gera o Showroom (pagina HTML autocontida + img/ + logo/) a partir das capturas.

Alvo visual: reference/showroom_2026-11-11/index.html (aprovado em 12/11/2026).
O template e o mesmo HTML, com os dados entrando por JSON. Mudar o visual =
mudar o template; mudar o conteudo = mudar os dados.

REGRA DURA: peca com celebridade/pessoa real nao vai para o Showroom
publicado. A revisao e humana: ``review.json`` na pasta do evento lista
``{"exclude": ["<marketplace>_<nn>", ...]}`` depois de olhar a folha de contato
(``shelfproof contact-sheet``). Os espacos pagos excluidos continuam contando
no ranking, sem imagem.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

TEMPLATES = Path(__file__).parent / "templates"
MKT_STYLE: Dict[str, Dict[str, str]] = {
    "amazon": {"key": "amazon", "name": "Amazon", "color": "#ff9900"},
    "mercadolivre": {"key": "ml", "name": "Mercado Livre", "color": "#ffe600"},
    "magalu": {"key": "magalu", "name": "Magalu", "color": "#0086ff"},
    "casasbahia": {"key": "cb", "name": "Casas Bahia", "color": "#1d4bff"},
    "shopee": {"key": "shopee", "name": "Shopee", "color": "#ee4d2d"},
    "midea": {"key": "midea", "name": "Loja Midea", "color": "#27a3e3"},
    "generic": {"key": "site", "name": "Site", "color": "#9aa4b8"},
}
KIND = {"paid": "paid", "marketplace": "own", "brand_store": "brand", "organic": "own"}
LOGO_DIR_DEFAULT = Path(__file__).resolve().parents[2] / "assets" / "logos"
DARK_LOGOS_DEFAULT = {"samsung", "intel", "acer", "apple", "neutrogena"}


def render(context: Dict[str, Any], data: Dict[str, Any], out_dir: Path) -> Path:
    """Escreve out_dir/index.html. As imagens/logos ja devem estar em out_dir/img e out_dir/logo."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    tpl = env.get_template("showroom.html.j2")
    out_dir.mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.render(data_json=data_json, **context)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return out_dir / "index.html"


def build_from_runs(run_dirs: Iterable[Path], out_dir: Path, event_label: str, date_label: str,
                    logo_dir: Optional[Path] = None, review: Optional[Dict[str, List[str]]] = None,
                    max_per_site: int = 18) -> Path:
    """Monta dados + imagens a partir de runs ja analisadas (pieces.json) e renderiza."""
    from PIL import Image

    logo_dir = logo_dir or LOGO_DIR_DEFAULT
    excluded = set((review or {}).get("exclude", []))
    out_dir = Path(out_dir)
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    (out_dir / "logo").mkdir(parents=True, exist_ok=True)

    mkts: Dict[str, Dict[str, str]] = {}
    pieces: List[Dict[str, Any]] = []
    extras: List[Dict[str, Any]] = []
    devices, sites = set(), []
    for rd in run_dirs:
        rd = Path(rd)
        manifest = json.loads((rd / "manifest.json").read_text(encoding="utf-8"))
        devices.add(manifest.get("device", "desktop"))
        raw = json.loads((rd / "pieces.json").read_text(encoding="utf-8"))
        style = MKT_STYLE.get(manifest.get("marketplace", "generic"), MKT_STYLE["generic"])
        key = style["key"]
        if key not in mkts:
            mkts[key] = {"name": style["name"], "color": style["color"]}
            sites.append(style["name"])
        n = sum(1 for p in pieces if p["m"] == key)
        # ordem de leitura: de cima para baixo na pagina
        raw.sort(key=lambda p: ((p.get("bbox") or {}).get("y", 1e9), p.get("position") or 99))
        for p in raw:
            img_file = (p.get("extra") or {}).get("image_file")
            row = {"m": key, "k": KIND.get(p["ownership"], "own"), "adv": p["advertiser"],
                   "slot": p.get("slot") or "", "pos": str(p.get("position") or "—"),
                   "title": p.get("title") or p.get("alt") or ""}
            if img_file and n < max_per_site:
                name = f"{key}_{n + 1:02d}"
                if name in excluded:
                    if p["ownership"] == "paid":
                        extras.append({k: row[k] for k in ("m", "adv", "slot", "title")})
                    n += 1
                    continue
                try:
                    im = Image.open(rd / "images" / img_file)
                    im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
                    if im.width < 300:
                        raise ValueError("pequena demais para o video wall")
                    if im.width > 1600:
                        im = im.resize((1600, int(im.height * 1600 / im.width)))
                    im.save(out_dir / "img" / f"{name}.webp", "WEBP", quality=82)
                    pieces.append(dict(row, img=name))
                    n += 1
                    continue
                except Exception:
                    pass
            if p["ownership"] == "paid":
                extras.append({k: row[k] for k in ("m", "adv", "slot", "title")})

    advs = {p["adv"] for p in pieces} | {x["adv"] for x in extras}
    logos: Dict[str, str] = {}
    for adv in sorted(advs):
        slug = adv.lower().replace("â", "a").replace("ó", "o").replace("+", "").replace(" ", "")
        src = logo_dir / f"{slug}.png"
        if src.exists():
            shutil.copy(src, out_dir / "logo" / src.name)
            logos[adv] = slug
    data = dict(date=date_label, mkts=mkts, logos=logos, dark_logos=sorted(DARK_LOGOS_DEFAULT & set(logos.values())),
                pieces=pieces, extras=extras)
    context = dict(
        page_title=f"ShelfProof {event_label} Showroom",
        header_line=f"COLETA {date_label} · {' + '.join(sorted(d.upper() for d in devices))} · {len(mkts)} PAGINAS",
        event_label=event_label,
        sites_text=", ".join(sites[:-1]) + (" e " + sites[-1] if len(sites) > 1 else (sites[0] if sites else "")),
        method_notes=[f"Fonte: capturas automaticas de {date_label} em sessao anonima limpa, com as imagens que o navegador baixou."],
    )
    (out_dir / "data.json").write_text(json.dumps(dict(context=context, data=data), ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return render(context, data, out_dir)
