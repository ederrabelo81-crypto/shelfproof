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
from datetime import datetime
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


def method_notes(date_label: str, sessions: Dict[str, str], empty_sites: List[str], excluded: int = 0,
                 n_rounds: int = 1, window: str = "", viewport_only: Optional[List[str]] = None) -> List[str]:
    """Como a leitura foi feita, dito com as condicoes REAIS de cada coleta (manifest.session)."""
    clean = [s for s, v in sessions.items() if v == "anon"]
    warm = [s for s, v in sessions.items() if v == "anon_warm"]
    logged = [s for s, v in sessions.items() if v == "profile"]
    notes = [f"Fonte: capturas automáticas de {date_label}, com as imagens que o navegador baixou."]
    if clean:
        notes.append(f"Sessão anônima limpa (sem login, sem histórico): {', '.join(clean)}.")
    if warm:
        notes.append(f"Sessão anônima aquecida (perfil dedicado, nunca logado, aquecido na home por causa do "
                     f"antibot): {', '.join(warm)}. Vitrines \"com base nas suas visualizações\" refletem esse perfil.")
    if logged:
        notes.append(f"Sessão logada (persona, vitrine personalizada): {', '.join(logged)}.")
    if viewport_only:
        notes.append(f"Celular em {', '.join(viewport_only)}: tela e toque de celular, com o navegador se "
                     "apresentando como desktop (com a identificação de Android as vitrines não carregavam). "
                     "O layout é o do celular; os anúncios podem ser os que o site escolhe para desktop.")
        notes.append("Mídia paga só com marcador concreto na página (rótulo, código de slot ou parâmetro de anúncio); "
                 "anunciante sem nome na página fica \"Não identificado\" ou é lido na própria peça.")
    notes.append("Espaços pagos sem imagem salva entram no ranking e aparecem na prova como registro de código.")
    if empty_sites:
        notes.append(f"Sem peça com imagem nesta coleta: {', '.join(empty_sites)}.")
    if excluded:
        notes.append(f"{excluded} peça(s) com pessoa real ficaram sem imagem nesta versão (o espaço pago continua no ranking).")
    if n_rounds > 1:
        notes.append(f"{n_rounds} rodadas de coleta ({window}). \"No ar\" é em quantas rodadas a peça apareceu "
                     "naquela home: é amostragem, não contagem de impressões.")
    else:
        notes.append("É a leitura de uma coleta, num instante: a vitrine gira ao longo do dia.")
    return notes


def render(context: Dict[str, Any], data: Dict[str, Any], out_dir: Path) -> Path:
    """Escreve out_dir/index.html. As imagens/logos ja devem estar em out_dir/img e out_dir/logo."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=select_autoescape(["html", "j2"]))
    tpl = env.get_template("showroom.html.j2")
    out_dir.mkdir(parents=True, exist_ok=True)
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = tpl.render(data_json=data_json, **context)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    return out_dir / "index.html"


def _creative_key(p: Dict[str, Any], base: str) -> str:
    """O mesmo criativo no mesmo slot, de uma rodada para outra (a posicao pode mudar)."""
    from shelfproof.pipeline import _path_key, _src_key

    ref = _src_key(p.get("img_src") or "") or _path_key(p.get("href") or "", base) or (p.get("title") or p.get("alt") or "")
    return f"{p.get('ownership')}|{p.get('slot') or ''}|{ref}"


def _hhmm(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except Exception:
        return ""


def _air(s: str) -> tuple:
    try:
        a, b = s.split("/")
        return int(a), int(b)
    except Exception:
        return 0, 0


def build_from_runs(run_dirs: Iterable[Path], out_dir: Path, event_label: str, date_label: str,
                    logo_dir: Optional[Path] = None, review: Optional[Dict[str, List[str]]] = None,
                    max_per_site: int = 18) -> Path:
    """Monta dados + imagens a partir de runs ja analisadas (pieces.json) e renderiza.

    Varias capturas do mesmo site e dispositivo (rodadas do dia) viram UMA tela: a peca vista em
    varias rodadas entra uma vez, com ``seen``/``of`` (rodadas em que apareceu / rodadas do site)
    e a janela ``t0``-``t1``. Nomes das imagens (os do review.json): ``<site>_<nn>`` no desktop e
    ``<site>_m_<nn>`` no celular, na ordem em que a peca apareceu (rodada, depois de cima para baixo),
    entao uma rodada nova nao renumera as pecas ja revisadas.
    """
    from PIL import Image

    logo_dir = logo_dir or LOGO_DIR_DEFAULT
    excluded = set((review or {}).get("exclude", []))
    out_dir = Path(out_dir)
    (out_dir / "img").mkdir(parents=True, exist_ok=True)
    (out_dir / "logo").mkdir(parents=True, exist_ok=True)

    # agrupa as capturas por (site, dispositivo), em ordem de horario
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for rd in run_dirs:
        rd = Path(rd)
        manifest = json.loads((rd / "manifest.json").read_text(encoding="utf-8"))
        style = MKT_STYLE.get(manifest.get("marketplace", "generic"), MKT_STYLE["generic"])
        dev = manifest.get("device", "desktop")
        groups.setdefault((style["key"], dev), []).append({"rd": rd, "manifest": manifest, "style": style})
    for runs in groups.values():
        runs.sort(key=lambda r: r["manifest"].get("collected_at", ""))
    devices = sorted({dev for _k, dev in groups}, key=lambda d: d != "desktop")
    multi_dev = len(devices) > 1

    sessions: Dict[str, str] = {}
    mkts: Dict[str, Dict[str, str]] = {}
    pieces: List[Dict[str, Any]] = []
    extras: List[Dict[str, Any]] = []
    sites: List[str] = []
    rounds_by: Dict[str, Dict[str, int]] = {}
    viewport_only: set = set()
    times: List[str] = []
    order = sorted(groups, key=lambda kd: (min(r["manifest"].get("collected_at", "") for r in groups[kd]),
                                           kd[1] != "desktop"))
    for key, dev in order:
        runs = groups[(key, dev)]
        style = runs[0]["style"]
        if key not in mkts:
            mkts[key] = {"name": style["name"], "color": style["color"]}
            sites.append(style["name"])
        rounds_by.setdefault(key, {})[dev] = len(runs)
        for r in runs:
            if dev == "mobile" and str(r["manifest"].get("emulation", "")).endswith(":viewport"):
                viewport_only.add(style["name"])
            sessions[style["name"] + (f" ({'celular' if dev == 'mobile' else 'desktop'})" if multi_dev else "")] = \
                r["manifest"].get("session", "anon")
            times.append(r["manifest"].get("collected_at", ""))

        # cada criativo, uma vez, com as rodadas em que apareceu
        agg: Dict[str, Dict[str, Any]] = {}
        for ri, r in enumerate(runs):
            raw = json.loads((r["rd"] / "pieces.json").read_text(encoding="utf-8"))
            raw.sort(key=lambda p: ((p.get("bbox") or {}).get("y", 1e9), p.get("position") or 99))
            base = r["manifest"].get("final_url") or r["manifest"].get("url", "")
            occ: Dict[str, int] = {}
            for p in raw:
                ck = _creative_key(p, base)
                occ[ck] = occ.get(ck, 0) + 1  # mesmo criativo duas vezes na MESMA captura = duas posicoes (S4)
                ck = f"{ck}#{occ[ck]}"
                a = agg.get(ck)
                if a is None:
                    a = agg[ck] = {"p": p, "rd": r["rd"], "first": ri, "y": (p.get("bbox") or {}).get("y", 1e9),
                                   "seen": [], "hits": 0, "frames": 0}
                a["seen"].append(r["manifest"].get("collected_at", ""))
                h, f = _air((p.get("extra") or {}).get("airtime_first_screen", ""))
                a["hits"] += h
                a["frames"] += f
                if not (a["p"].get("extra") or {}).get("image_file") and (p.get("extra") or {}).get("image_file"):
                    a["p"], a["rd"] = p, r["rd"]  # fica com a rodada que tem a imagem
        items = sorted(agg.values(), key=lambda a: (a["first"], a["y"], a["p"].get("position") or 99))

        prefix = f"{key}_m_" if dev == "mobile" else f"{key}_"
        n = 0
        for a in items:
            p, rd = a["p"], a["rd"]
            img_file = (p.get("extra") or {}).get("image_file")
            row = {"m": key, "d": dev, "k": KIND.get(p["ownership"], "own"), "adv": p["advertiser"],
                   "slot": p.get("slot") or "", "pos": str(p.get("position") or "—"),
                   "title": p.get("title") or p.get("alt") or "",
                   "seen": len(a["seen"]), "of": len(runs),
                   "t0": _hhmm(min(a["seen"])), "t1": _hhmm(max(a["seen"]))}
            if a["frames"]:
                row["air"] = f"{a['hits']}/{a['frames']}"
            if img_file and n < max_per_site:
                name = f"{prefix}{n + 1:02d}"
                if name in excluded:
                    if p["ownership"] == "paid":
                        extras.append({k: v for k, v in row.items() if k not in ("k", "pos")})
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
                extras.append({k: v for k, v in row.items() if k not in ("k", "pos")})

    advs = {p["adv"] for p in pieces} | {x["adv"] for x in extras}
    logos: Dict[str, str] = {}
    for adv in sorted(advs):
        slug = adv.lower().replace("â", "a").replace("ó", "o").replace("+", "").replace(" ", "")
        src = logo_dir / f"{slug}.png"
        if src.exists():
            shutil.copy(src, out_dir / "logo" / src.name)
            logos[adv] = slug
    n_rounds = max((n for d in rounds_by.values() for n in d.values()), default=0)
    times = sorted(t for t in times if t)
    window = f"{_hhmm(times[0])}–{_hhmm(times[-1])}" if times else ""
    data = dict(date=date_label, mkts=mkts, logos=logos, dark_logos=sorted(DARK_LOGOS_DEFAULT & set(logos.values())),
                pieces=pieces, extras=extras, devices=devices, rounds=rounds_by, window=window)
    header = f"COLETA {date_label} · {' + '.join(d.upper() for d in devices)} · {len(mkts)} PAGINAS"
    if n_rounds > 1:
        header += f" · {n_rounds} RODADAS {window}"
    context = dict(
        page_title=f"ShelfProof {event_label} Showroom",
        header_line=header,
        event_label=event_label,
        sites_text=", ".join(sites[:-1]) + (" e " + sites[-1] if len(sites) > 1 else (sites[0] if sites else "")),
        method_notes=method_notes(date_label, sessions, [m["name"] for k, m in mkts.items()
                                                       if not any(p["m"] == k for p in pieces)], len(excluded),
                                  n_rounds=n_rounds, window=window, viewport_only=sorted(viewport_only)),
    )
    (out_dir / "data.json").write_text(json.dumps(dict(context=context, data=data), ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return render(context, data, out_dir)
