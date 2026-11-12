"""Site estatico com os Showrooms publicados (Vercel).

    site/
      index.html          lista dos eventos (gerada a cada publicacao)
      vercel.json         URLs limpas
      2026-11-12/         copia do Showroom do dia (index.html + img/ + logo/ + data.json)

O site fica FORA do git (site/ no .gitignore): as pecas sao criativos de terceiros e o
repositorio e publico. Publicar = gerar a pasta e subir com a CLI da Vercel
(scripts/publicar_site.bat).
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List

SKIP = {"contact_sheet.jpg", "review.json"}


def add_showroom(showroom_dir: Path, site_dir: Path, slug: str) -> Path:
    """Copia o Showroom para site/<slug>/ e refaz o indice."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{0,60}", slug):
        raise ValueError(f"slug invalido para URL: {slug!r} (use algo como 2026-11-12 ou black-friday-2026)")
    showroom_dir, site_dir = Path(showroom_dir), Path(site_dir)
    if not (showroom_dir / "index.html").exists() or not (showroom_dir / "data.json").exists():
        raise FileNotFoundError(f"{showroom_dir} nao tem index.html e data.json (rode o comando showroom antes)")
    dest = site_dir / slug
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(showroom_dir, dest, ignore=lambda d, names: [n for n in names if n in SKIP])
    # trailingSlash: /2026-11-12 vira /2026-11-12/. Sem a barra, img/x.webp resolveria para /img/x.webp
    # (fora da pasta do evento) e a pagina abriria sem pecas.
    (site_dir / "vercel.json").write_text(json.dumps({"cleanUrls": True, "trailingSlash": True}, indent=1),
                                          encoding="utf-8")
    write_index(site_dir)
    return dest


def _summary(event_dir: Path) -> Dict[str, Any]:
    d = json.loads((event_dir / "data.json").read_text(encoding="utf-8"))
    ctx, data = d["context"], d["data"]
    rows = data["pieces"] + [dict(r, k="paid") for r in data.get("extras", [])]
    paid = [r for r in rows if r["k"] == "paid"]
    named = [r for r in paid if not re.fullmatch(r"(?i)n[aã]o identificado", r["adv"] or "")]
    count: Dict[str, int] = {}
    for r in named:
        count[r["adv"]] = count.get(r["adv"], 0) + 1
    top = sorted(count.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    return {"slug": event_dir.name, "event": ctx.get("event_label", event_dir.name), "date": data.get("date", ""),
            "header": ctx.get("header_line", ""), "sites": len(data.get("mkts", {})), "paid": len(paid),
            "advertisers": len(count), "top": top}


def _date_key(s: Dict[str, Any]) -> str:
    m = re.match(r"(\d{2})/(\d{2})/(\d{4})", s["date"])
    return f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else s["slug"]


def write_index(site_dir: Path) -> Path:
    events: List[Dict[str, Any]] = []
    for d in sorted(Path(site_dir).iterdir()):
        if d.is_dir() and (d / "data.json").exists():
            events.append(_summary(d))
    events.sort(key=_date_key, reverse=True)
    cards = []
    for e in events:
        top = " · ".join(f"{html.escape(a)} {n}" for a, n in e["top"]) or "sem anunciante identificado"
        cards.append(
            f'<a class="ev" href="{html.escape(e["slug"])}/">'
            f'<span class="dt">{html.escape(e["date"])}</span>'
            f'<span class="nm">{html.escape(e["event"])}</span>'
            f'<span class="kp"><b>{e["paid"]}</b> espaços pagos · <b>{e["advertisers"]}</b> anunciantes · '
            f'<b>{e["sites"]}</b> páginas</span>'
            f'<span class="tp">{top}</span></a>')
    body = "\n".join(cards) or '<p class="empty">Nenhum Showroom publicado ainda.</p>'
    page = f"""<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ShelfProof Showrooms</title>
<style>
:root {{ --ink:#0a0c11; --panel:#12161f; --line:#242a37; --text:#edf0f5; --muted:#8b94a7; --paid:#ffb02e; color-scheme: dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--ink); color:var(--text); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }}
main {{ max-width: 960px; margin: 0 auto; padding: 48px 16px; display:flex; flex-direction:column; gap:28px; }}
h1 {{ font-size: clamp(32px, 6vw, 56px); line-height:1; letter-spacing:-.03em; margin:0; }}
h1 b {{ color: var(--paid); }}
p.lede {{ color: var(--muted); margin: 0; max-width: 60ch; line-height:1.5; }}
.list {{ display:grid; gap:12px; }}
.ev {{ display:grid; gap:6px; padding:18px; background:var(--panel); border:1px solid var(--line); border-radius:14px; text-decoration:none; color:inherit; }}
.ev:hover {{ border-color:#3a4256; }}
.dt {{ font-family: ui-monospace, Menlo, Consolas, monospace; font-size:12px; color:var(--muted); }}
.nm {{ font-size:24px; font-weight:700; letter-spacing:-.01em; }}
.kp {{ font-size:14px; color:var(--muted); }} .kp b {{ color: var(--text); }}
.tp {{ font-size:13px; color: var(--paid); }}
.empty {{ color: var(--muted); }}
</style></head>
<body><main>
<h1>Shelf<b>Proof</b> · Showrooms</h1>
<p class="lede">Quem comprou a vitrine dos marketplaces em cada coleta: peças reais, ranking de anunciantes e prova de veiculação.</p>
<div class="list">
{body}
</div>
</main></body></html>
"""
    out = Path(site_dir) / "index.html"
    out.write_text(page, encoding="utf-8")
    return out
