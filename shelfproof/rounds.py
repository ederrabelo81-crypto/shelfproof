"""Coleta do dia em rodadas.

Cada ``python -m shelfproof event`` e UMA rodada: captura todas as homes (desktop + celular)
e registra o que saiu em ``runs/showroom/<AAAA-MM-DD>/rounds.json``. O Showroom do dia e
refeito a cada rodada somando todas: a mesma peca vista em varias rodadas vira uma so, com
"no ar em X de Y rodadas" e a janela de horario (amostragem, nao contagem de impressoes).

    runs/showroom/2026-11-17/
      rounds.json        [{"round": 1, "started_at": ..., "event": ..., "runs": [{site, device, ok, run_dir...}]}]
      review.json        (opcional) {"exclude": ["ml_04", "ml_m_02"]} depois da folha de contato
      index.html img/ logo/ data.json
"""
from __future__ import annotations

import json
import shutil
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

DEFAULT_EVENT = "Vitrine do dia"


def parse_date(s: str) -> date:
    """DD/MM/AAAA ou AAAA-MM-DD."""
    s = s.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"data invalida: {s!r} (use DD/MM/AAAA)")


def day_dir(out_root: Path, day: date) -> Path:
    return Path(out_root) / "showroom" / day.isoformat()


def load_rounds(sdir: Path) -> List[Dict[str, Any]]:
    f = Path(sdir) / "rounds.json"
    if not f.exists():
        return []
    return json.loads(f.read_text(encoding="utf-8"))


def add_round(sdir: Path, started: datetime, runs: List[Dict[str, Any]], event: Optional[str] = None) -> int:
    """Acrescenta uma rodada ao rounds.json do dia. Devolve o numero da rodada."""
    sdir = Path(sdir)
    sdir.mkdir(parents=True, exist_ok=True)
    rounds = load_rounds(sdir)
    n = len(rounds) + 1
    rounds.append({"round": n, "started_at": started.isoformat(), "event": event, "runs": runs})
    (sdir / "rounds.json").write_text(json.dumps(rounds, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def day_run_dirs(sdir: Path, devices: Optional[List[str]] = None) -> List[Path]:
    """Capturas uteis de todas as rodadas do dia: nao bloqueadas e com pieces.json.

    Vale o que esta no disco, nao o ``ok`` da hora da rodada: uma captura cuja analise falhou
    (ex.: faltou o lxml no PC, 17/11/2026) entra depois de ``shelfproof analyze <pasta>``.
    """
    out: List[Path] = []
    for r in load_rounds(sdir):
        for row in r.get("runs", []):
            if row.get("blocked") or not row.get("run_dir") or (devices and row.get("device") not in devices):
                continue
            rd = Path(row["run_dir"])
            if (rd / "pieces.json").exists() and (rd / "manifest.json").exists():
                out.append(rd)
            elif row.get("ok"):
                logger.warning(f"rodada {r['round']}: {rd} sem pieces.json (pasta apagada?)")
            elif (rd / "page.html").exists():
                logger.warning(f"rodada {r['round']}: {rd} capturada mas nao analisada: "
                               f"python -m shelfproof analyze {rd}")
    return out


def build_day(sdir: Path, event: Optional[str] = None, devices: Optional[List[str]] = None) -> Optional[Path]:
    """Refaz o Showroom do dia com todas as rodadas. None se nao ha captura util."""
    from shelfproof.render.showroom import build_from_runs

    sdir = Path(sdir)
    rounds = load_rounds(sdir)
    runs = day_run_dirs(sdir, devices)
    if not runs:
        return None
    if not event:
        event = next((r["event"] for r in reversed(rounds) if r.get("event")), None) or DEFAULT_EVENT
    review = None
    if (sdir / "review.json").exists():
        review = json.loads((sdir / "review.json").read_text(encoding="utf-8"))
    for sub in ("img", "logo"):  # sem sobra da montagem anterior
        shutil.rmtree(sdir / sub, ignore_errors=True)
    day = date.fromisoformat(sdir.name) if len(sdir.name) == 10 else None
    label = day.strftime("%d/%m/%Y") if day else sdir.name
    return build_from_runs(runs, sdir, event, label, review=review)
