"""Linha de comando do Shelf Proof.

    python -m shelfproof capture https://www.magazineluiza.com.br/ --device both
    python -m shelfproof analyze runs/2026-11-27/magazineluiza-com-br_desktop_anon_080102
    python -m shelfproof detect-file pagina_salva.html
    python -m shelfproof event                                # 1 rodada do dia (desktop + celular)
    python -m shelfproof event --event "Black Friday" --date 27/11/2026
    python -m shelfproof event --rebuild                      # refaz o Showroom do dia (review.json)
    python -m shelfproof showroom --event "Black Friday" --date 27/11/2026 --out out/bf <run_dir> ...
    python -m shelfproof contact-sheet out/bf
    python -m shelfproof analyze --vision <run_dir>          # fase 3: anunciante lido na imagem
    python -m shelfproof vision-eval                          # mede a leitura visual no 11.11
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import List

from loguru import logger


def _reader(a: argparse.Namespace):
    """Leitor visual quando --vision foi pedido (None = desligado)."""
    if not getattr(a, "vision", False):
        return None
    from shelfproof.vision.advertiser import default_reader

    return default_reader()


def _cmd_capture(a: argparse.Namespace) -> int:
    from shelfproof.collect.capture import CaptureConfig, capture
    from shelfproof.pipeline import analyze

    devices = ["desktop", "mobile"] if a.device == "both" else [a.device]
    reader = _reader(a)
    rc = 0
    for dev in devices:
        res = capture(CaptureConfig(url=a.url, device=dev, session=a.session, engine=a.engine,
                                    out_root=Path(a.out), carousel_seconds=a.carousel, headless=a.headless))
        if res.ok:
            ps = analyze(res.run_dir, reader=reader)
            paid = Counter(p.advertiser for p in ps if p.is_paid)
            logger.info(f"[{dev}] {len(ps)} pecas, {sum(paid.values())} pagas: {dict(paid.most_common(8))}")
        else:
            rc = 2
            logger.error(f"[{dev}] captura sem resultado util: {res.errors[-3:]}")
        print(res.run_dir)
    return rc


def _cmd_analyze(a: argparse.Namespace) -> int:
    from shelfproof.pipeline import analyze

    reader = _reader(a)
    for rd in a.run_dirs:
        analyze(Path(rd), reader=reader)
        print(json.dumps(json.loads((Path(rd) / "summary.json").read_text(encoding="utf-8")), ensure_ascii=False, indent=1))
    return 0


def _cmd_detect_file(a: argparse.Namespace) -> int:
    from shelfproof.detect.rules import detect

    html = Path(a.html).read_text(encoding="utf-8", errors="ignore")
    for p in detect(html, a.url or ""):
        if a.paid_only and not p.is_paid:
            continue
        print(f"{p.marketplace:12} {p.ownership:12} {p.ad_format:17} {p.advertiser:18} {p.slot[:42]:42} {p.title[:50]}")
    return 0


def _cmd_showroom(a: argparse.Namespace) -> int:
    from shelfproof.render.showroom import build_from_runs

    review = json.loads(Path(a.review).read_text(encoding="utf-8")) if a.review else None
    out = build_from_runs([Path(r) for r in a.run_dirs], Path(a.out), a.event, a.date, review=review)
    print(out)
    return 0


def _cmd_contact(a: argparse.Namespace) -> int:
    from shelfproof.render.contact_sheet import contact_sheet

    print(contact_sheet(Path(a.showroom_dir), Path(a.showroom_dir) / "contact_sheet.jpg"))
    return 0


def _cmd_event(a: argparse.Namespace) -> int:
    """UMA rodada: captura todos os alvos (desktop + celular, sem login), analisa e refaz o
    Showroom do dia somando todas as rodadas ja feitas (runs/showroom/<AAAA-MM-DD>/rounds.json).
    Rodar de novo no mesmo dia = mais uma rodada (rotacao e tempo no ar ao longo do dia)."""
    from shelfproof.collect.capture import CaptureConfig, capture, now_brt
    from shelfproof.pipeline import analyze
    from shelfproof.rounds import add_round, build_day, day_dir, parse_date

    day = parse_date(a.date) if a.date else now_brt().date()
    sdir = day_dir(Path(a.out), day)
    if a.rebuild:
        out = build_day(sdir, a.event, devices=_devices(a.showroom_device))
        print(out if out else "Nenhuma rodada registrada neste dia")
        return 0 if out else 2

    try:  # log da rodada em arquivo, alem do console (para conferir depois o que falhou)
        Path("logs").mkdir(exist_ok=True)
        logger.add(f"logs/coleta_{day.isoformat()}.log", level="INFO", encoding="utf-8")
    except Exception as exc:
        logger.warning(f"log em arquivo indisponivel: {exc}")
    missing = _missing_deps()
    if missing:  # antes de abrir o Chrome: sem eles a rodada captura e nao classifica nada
        logger.error(f"Faltam pacotes no Python deste PC: {', '.join(missing)}. "
                     f"Rode: {sys.executable} -m pip install -r requirements.txt")
        return 3
    targets = json.loads(Path(a.targets).read_text(encoding="utf-8"))["targets"]
    only = {s.strip().lower() for s in (a.only or "").split(",") if s.strip()}
    if only:
        targets = [t for t in targets if t["name"].lower() in only]
    reader = _reader(a)
    started = now_brt()
    done: List[dict] = []
    for t in targets:
        for dev in t.get("devices", ["desktop", "mobile"]):
            if dev not in _devices(a.devices):
                continue
            session = t.get("session", "anon")
            try:
                res = capture(CaptureConfig(url=t["url"], device=dev, session=session, out_root=Path(a.out),
                                            carousel_seconds=a.carousel,
                                            mobile_emulation=t.get("mobile_emulation", "")))
            except Exception as exc:  # um site nao derruba a rodada
                logger.error(f"{t['url']} ({dev}): {exc}")
                done.append({"site": t["name"], "device": dev, "ok": False, "error": str(exc)})
                continue
            row = {"site": t["name"], "device": dev, "session": session, "ok": bool(res.ok),
                   "blocked": bool(res.blocked), "run_dir": str(res.run_dir)}
            if res.ok:
                try:
                    ps = analyze(res.run_dir, reader=reader)
                    row.update(pieces=len(ps), paid=sum(1 for p in ps if p.is_paid))
                except Exception as exc:
                    row.update(ok=False, error=f"analise: {exc}")
                    logger.error(f"{t['url']} ({dev}) analise: {exc}")
            else:
                row["error"] = "; ".join(res.errors[-2:])
            done.append(row)
    rnd = add_round(sdir, started, done, a.event)
    print(f"Rodada {rnd} de {day.strftime('%d/%m/%Y')}:")
    for r in done:
        st = "OK" if r["ok"] else ("BLOQUEADO" if r.get("blocked") else "FALHOU")
        extra = f"{r.get('pieces', 0)} pecas, {r.get('paid', 0)} pagas" if r["ok"] else r.get("error", "")
        print(f"  {st:9} {r['site']:14} {r['device']:7} {extra}")
    out = build_day(sdir, a.event, devices=_devices(a.showroom_device))
    if not out:
        logger.error("Nenhuma captura util no dia: nada para montar")
        return 2
    print(out)
    return 0 if all(r["ok"] for r in done) else 1


def _cmd_today(a: argparse.Namespace) -> int:
    """Data de hoje em BRT (AAAA-MM-DD): os .bat usam para achar a pasta do dia."""
    from shelfproof.collect.capture import now_brt

    print(now_brt().date().isoformat())
    return 0


def _missing_deps() -> List[str]:
    """Pacotes que a analise precisa (o detector usa o parser lxml do BeautifulSoup)."""
    import importlib.util

    return [m for m in ("lxml", "bs4", "PIL", "jinja2") if importlib.util.find_spec(m) is None]


def _devices(v: str) -> List[str]:
    return ["desktop", "mobile"] if v == "both" else [v]


def _cmd_site(a: argparse.Namespace) -> int:
    from shelfproof.render.site import add_showroom

    dest = add_showroom(Path(a.showroom_dir), Path(a.out), a.slug)
    print(dest)
    print(f"Publicar: npx --yes vercel@latest deploy {a.out} --prod --yes --project {a.project} --create-if-missing")
    return 0


def _cmd_vision_eval(a: argparse.Namespace) -> int:
    from shelfproof.vision.evaluate import evaluate_reference

    from shelfproof.vision.advertiser import default_reader

    reader = default_reader()
    if reader is None:
        return 2
    rep = evaluate_reference(reader, limit=a.limit)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0 if rep["wrong"] == 0 else 1


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shelfproof", description="Prova de vitrine: quem comprou cada espaco")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capture", help="captura uma URL (print, HTML, imagens) e analisa")
    c.add_argument("url")
    c.add_argument("--device", choices=["desktop", "mobile", "both"], default="desktop")
    c.add_argument("--session", choices=["anon", "anon_warm", "profile"], default="anon",
                   help="anon_warm: perfil dedicado nunca logado, aquecido na home (Magalu/Casas Bahia; so desktop)")
    c.add_argument("--engine", choices=["cdp", "launch"], default="cdp")
    c.add_argument("--carousel", type=float, default=24.0, help="segundos observando a 1a tela")
    c.add_argument("--headless", action="store_true", help="so com --engine launch (testes/CI)")
    c.add_argument("--out", default="runs")
    c.add_argument("--vision", action="store_true", help="le na imagem o anunciante das pagas sem nome (Claude API)")
    c.set_defaults(fn=_cmd_capture)

    c = sub.add_parser("analyze", help="(re)classifica capturas ja feitas")
    c.add_argument("run_dirs", nargs="+")
    c.add_argument("--vision", action="store_true", help="le na imagem o anunciante das pagas sem nome (Claude API)")
    c.set_defaults(fn=_cmd_analyze)

    c = sub.add_parser("detect-file", help="classifica um HTML salvo (Ctrl+S)")
    c.add_argument("html")
    c.add_argument("--url", default="")
    c.add_argument("--paid-only", action="store_true")
    c.set_defaults(fn=_cmd_detect_file)

    c = sub.add_parser("showroom", help="monta o Showroom a partir de capturas analisadas")
    c.add_argument("run_dirs", nargs="+")
    c.add_argument("--event", required=True)
    c.add_argument("--date", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--review", help="review.json com {'exclude': [...]}")
    c.set_defaults(fn=_cmd_showroom)

    c = sub.add_parser("contact-sheet", help="folha de contato para a revisao humana")
    c.add_argument("showroom_dir")
    c.set_defaults(fn=_cmd_contact)

    c = sub.add_parser("event", help="uma rodada: captura todos os alvos e refaz o Showroom do dia")
    c.add_argument("--targets", default="config/targets.json")
    c.add_argument("--event", default=None, help="nome no Showroom (ex.: Black Friday; padrao: o da 1a rodada "
                   "do dia ou 'Vitrine do dia')")
    c.add_argument("--date", default="", help="DD/MM/AAAA (padrao: hoje, BRT)")
    c.add_argument("--devices", choices=["desktop", "mobile", "both"], default="both",
                   help="o que capturar nesta rodada (respeita os devices de cada alvo)")
    c.add_argument("--only", default="", help="so estes alvos, pelo nome: \"Magalu,Casas Bahia\"")
    c.add_argument("--showroom-device", choices=["desktop", "mobile", "both"], default="both")
    c.add_argument("--carousel", type=float, default=24.0, help="segundos observando a 1a tela")
    c.add_argument("--rebuild", action="store_true",
                   help="nao captura: so refaz o Showroom do dia (ex.: depois do review.json)")
    c.add_argument("--out", default="runs")
    c.add_argument("--vision", action="store_true", help="le na imagem o anunciante das pagas sem nome (Claude API)")
    c.set_defaults(fn=_cmd_event)

    c = sub.add_parser("today", help="data de hoje em BRT (AAAA-MM-DD), para os scripts")
    c.set_defaults(fn=_cmd_today)

    c = sub.add_parser("site", help="copia um Showroom para o site estatico (site/<slug>) e refaz o indice")
    c.add_argument("showroom_dir")
    c.add_argument("--slug", required=True, help="parte da URL, ex.: 2026-11-12 ou black-friday-2026")
    c.add_argument("--out", default="site")
    c.add_argument("--project", default="shelfproof-showroom", help="nome do projeto na Vercel")
    c.set_defaults(fn=_cmd_site)

    c = sub.add_parser("vision-eval", help="mede a leitura visual nas pecas pagas do 11.11 (gasta API)")
    c.add_argument("--limit", type=int, default=0, help="0 = todas")
    c.set_defaults(fn=_cmd_vision_eval)

    try:  # .env do PC coletor (RAC_*, ANTHROPIC_API_KEY)
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
