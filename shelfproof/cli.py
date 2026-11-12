"""Linha de comando do Shelf Proof.

    python -m shelfproof capture https://www.magazineluiza.com.br/ --device both
    python -m shelfproof analyze runs/2026-11-27/magazineluiza-com-br_desktop_anon_080102
    python -m shelfproof detect-file pagina_salva.html
    python -m shelfproof event --targets config/targets.json --event "Black Friday" --date 27/11/2026
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
    if a.session == "anon_warm" and "mobile" in devices:
        logger.warning("anon_warm so existe em desktop: o celular nao sera capturado nesta sessao")
        devices = [d for d in devices if d == "desktop"]
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
    """Captura todos os alvos (desktop + mobile, anonimo), analisa e monta o Showroom."""
    from shelfproof.collect.capture import CaptureConfig, capture
    from shelfproof.pipeline import analyze
    from shelfproof.render.showroom import build_from_runs

    targets = json.loads(Path(a.targets).read_text(encoding="utf-8"))["targets"]
    reader = _reader(a)
    runs: List[Path] = []
    for t in targets:
        for dev in t.get("devices", ["desktop", "mobile"]):
            # anon_warm (targets.json) so existe em desktop; o celular segue no contexto limpo
            session = t.get("session", "anon")
            if session == "anon_warm" and dev != "desktop":
                session = "anon"
            try:
                res = capture(CaptureConfig(url=t["url"], device=dev, session=session, out_root=Path(a.out)))
            except Exception as exc:  # um site nao derruba o evento
                logger.error(f"{t['url']} ({dev}): {exc}")
                continue
            if res.ok:
                analyze(res.run_dir, reader=reader)
                if dev == a.showroom_device:
                    runs.append(res.run_dir)
    if not runs:
        logger.error("Nenhuma captura util: nada para montar")
        return 2
    slug = a.event.lower().replace(" ", "-").replace(".", "")
    out = build_from_runs(runs, Path(a.out) / "showroom" / slug, a.event, a.date)
    print(out)
    return 0


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

    c = sub.add_parser("event", help="captura todos os alvos e monta o Showroom do evento")
    c.add_argument("--targets", default="config/targets.json")
    c.add_argument("--event", required=True)
    c.add_argument("--date", required=True)
    c.add_argument("--showroom-device", default="desktop")
    c.add_argument("--out", default="runs")
    c.add_argument("--vision", action="store_true", help="le na imagem o anunciante das pagas sem nome (Claude API)")
    c.set_defaults(fn=_cmd_event)

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
