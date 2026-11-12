"""Robo de coleta: abre a pagina como um cliente, fotografa e guarda a evidencia.

Uma captura = uma URL x um dispositivo x um tipo de sessao, num instante.
Gera uma pasta ``runs/<data>/<marketplace>_<device>_<sessao>_<HHMM>/`` com:

    manifest.json   URL, horario (BRT), dispositivo, sessao, altura, erros
    page.html       DOM renderizado depois da rolagem (entrada do detector)
    elements.json   toda <img>: src real, alt, link, caixa na pagina, rotulos
    full.jpg        print da pagina inteira
    frames/         prints da 1a tela a cada N s (rotacao do carrossel)
    images/         bytes das imagens que o navegador baixou (o criativo real)
    images.json     url -> arquivo

REGRAS DURAS herdadas do RAC Position Tracker (ver .claude/COMMON_MISTAKES.md):
* Chrome COMUM + CDP (rebrowser-playwright), nunca launch_persistent_context
  em site com antibot (#10). O modo ``launch`` existe so para sites sem antibot
  e para testes.
* Um unico sync_playwright por thread: sempre via ``playwright_runtime`` (#21).
* Chrome morto != bloqueio (#22). Bloqueio se decide por evidencia (#15):
  sem imagem de produto/banner + frase de captcha = bloqueio; frase sozinha nao.
* Cada artefato e gravado no seu proprio try/except (#18): um print que falha
  nao pode levar o HTML junto.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from loguru import logger

from shelfproof.detect.rules import identify_marketplace

BRT = timezone(timedelta(hours=-3))

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36"
)
# UA sempre da familia Chromium: o engine e Chrome (COMMON_MISTAKES #14).
DEVICES: Dict[str, Dict[str, Any]] = {
    "desktop": dict(viewport={"width": 1440, "height": 900}, user_agent=DESKTOP_UA,
                    device_scale_factor=1, is_mobile=False, has_touch=False),
    "mobile": dict(viewport={"width": 412, "height": 915}, user_agent=MOBILE_UA,
                   device_scale_factor=2.625, is_mobile=True, has_touch=True),
}
CONTEXT_COMMON = dict(locale="pt-BR", timezone_id="America/Sao_Paulo")

BLOCK_PHRASES = re.compile(
    r"captcha|n[aã]o sou um rob[oô]|verifique que voc[eê] [eé] humano|access denied|"
    r"acesso negado|unusual traffic|pardon our interruption|/gz/account-verification|"
    # pagina de bloqueio do Akamai na Magalu (12/11/2026): "Nao e possivel acessar a pagina (Erro 403)"
    r"n[aã]o [eé] poss[ií]vel acessar a p[aá]gina|erro 403|403 forbidden",
    re.I,
)
BLOCK_STATUS = {403, 429}
# Sites com Akamai Bot Manager: no aquecimento, esperar o cookie _abck validar (~0~)
AKAMAI_HOSTS = ("magazineluiza.com.br", "casasbahia.com.br")
SESSIONS = ("anon", "anon_warm", "profile")

# Coleta todas as <img> visiveis com a caixa na pagina inteira e os sinais que o
# detector usa (link, rotulo de patrocinio por perto, slot-id da Amazon).
ELEMENTS_JS = r"""
() => {
  const LABEL = /^(patrocinad[oa]s?|publicidade|an[uú]ncio|sponsored)$/i;
  const out = [];
  const sy = window.scrollY, sx = window.scrollX;
  document.querySelectorAll('img').forEach((img, i) => {
    const r = img.getBoundingClientRect();
    if (r.width < 24 || r.height < 24) return;
    const a = img.closest('a');
    let label = '', slotId = '', node = img;
    for (let k = 0; k < 6 && node; k++) {
      node = node.parentElement;
      if (!node) break;
      if (!slotId && node.dataset && node.dataset.csaCSlotId) slotId = node.dataset.csaCSlotId;
      if (!label) {
        for (const el of node.querySelectorAll('span,div,p,small,b')) {
          const t = (el.textContent || '').trim();
          if (t.length < 14 && LABEL.test(t)) { label = t; break; }
        }
      }
    }
    // visibilidade EFETIVA: opacidade/visibility dos ancestores + quem esta por cima
    let op = 1, hidden = false;
    for (let n = img; n && n !== document.documentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      op *= parseFloat(cs.opacity || '1');
      if (cs.visibility === 'hidden' || cs.display === 'none') { hidden = true; break; }
    }
    let onTop = null;
    if (r.bottom > 0 && r.top < window.innerHeight && r.right > 0 && r.left < window.innerWidth) {
      const cx = Math.min(Math.max(r.left + r.width / 2, 1), window.innerWidth - 1);
      const cy = Math.min(Math.max(r.top + r.height / 2, 1), window.innerHeight - 1);
      const hit = document.elementFromPoint(cx, cy);
      onTop = !!hit && (hit === img || img.contains(hit) || (a && a.contains(hit)));
    }
    out.push({
      i, src: img.currentSrc || img.src || '', alt: img.alt || '',
      href: a ? a.href : '',
      x: r.left + sx, y: r.top + sy, w: r.width, h: r.height,
      nw: img.naturalWidth, nh: img.naturalHeight,
      // on_top e so informativo: camada com opacidade 0 por cima ainda "recebe" o ponto
      visible: !hidden && op > 0.05,
      opacity: Math.round(op * 100) / 100, on_top: onTop,
      label, slot_id: slotId,
    });
  });
  return out;
}
"""


@dataclass
class CaptureConfig:
    url: str
    device: str = "desktop"            # desktop | mobile
    session: str = "anon"              # anon (contexto limpo) | anon_warm (perfil dedicado nunca logado,
                                       # aquecido) | profile (perfil logado = persona)
    engine: str = "cdp"                # cdp (Chrome comum) | launch (so sites sem antibot / testes)
    out_root: Path = Path("runs")
    carousel_seconds: float = 24.0     # quanto tempo observar a 1a tela girando
    carousel_interval: float = 3.0
    max_scroll_steps: int = 40
    min_image_bytes: int = 4_000       # ignora icones/pixels de rastreio
    headless: bool = False             # so vale para engine=launch


@dataclass
class CaptureResult:
    run_dir: Path
    marketplace: str
    ok: bool
    blocked: bool = False
    errors: List[str] = field(default_factory=list)


def now_brt() -> datetime:
    return datetime.now(BRT)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


IMAGE_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
             "image/gif": ".gif", "image/avif": ".avif"}
GENERIC_TYPES = ("application/octet-stream", "binary/octet-stream", "")


def sniff_image_type(body: bytes) -> str:
    """Tipo da imagem pelos primeiros bytes (para servidor que manda octet-stream)."""
    if body[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if body[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "image/webp"
    if body[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if body[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    return ""


def _is_candidate(ctype: str) -> bool:
    c = ctype.split(";")[0].strip().lower()
    return (c.startswith("image/") and "svg" not in c) or c in GENERIC_TYPES


class _ImageSink:
    """Guarda os bytes das imagens que a pagina baixa (o criativo exato que foi ao ar).

    O handler de ``response`` so ANOTA a resposta. Ler o corpo (``response.body()``)
    dentro do handler e uma ida e volta ao navegador no meio do despacho de eventos:
    no Windows (Playwright 1.60) isso falhava sempre, em silencio, e a captura saia
    com 0 imagens (12/11/2026). Os corpos sao lidos depois, em ``flush()``, e o que
    faltar e buscado de novo pelo endereco em ``fetch_missing()``.
    """

    def __init__(self, folder: Path, min_bytes: int) -> None:
        self.folder = folder
        self.min_bytes = min_bytes
        self.index: Dict[str, str] = {}
        self.pending: List[Any] = []
        self.failures: List[str] = []
        folder.mkdir(parents=True, exist_ok=True)

    def on_response(self, response: Any) -> None:
        try:
            ctype = (response.headers or {}).get("content-type", "")
            # redirect (3xx) nao tem corpo: o destino chega como outra resposta (pixel de rastreio da Magalu)
            if 300 <= int(getattr(response, "status", 200) or 200) < 400:
                return
            if _is_candidate(ctype) and response.request.resource_type in ("image", "other", "fetch"):
                self.pending.append(response)
        except Exception as exc:
            self._fail("resposta", exc)

    def _fail(self, what: str, exc: Exception) -> None:
        if len(self.failures) < 5:  # amostra para o manifest; nunca silencioso
            self.failures.append(f"{what}: {type(exc).__name__}: {str(exc)[:160]}")

    def _save(self, url: str, ctype: str, body: bytes) -> None:
        if url in self.index or len(body) < self.min_bytes:
            return
        if not ctype.startswith("image/"):
            ctype = sniff_image_type(body)
            if not ctype:
                return  # octet-stream que nao e imagem
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + IMAGE_EXT.get(ctype.split(";")[0].strip(), ".img")
        (self.folder / name).write_bytes(body)
        self.index[url] = name

    def flush(self) -> None:
        """Le os corpos das respostas anotadas (fora do handler de eventos)."""
        pending, self.pending = self.pending, []
        for resp in pending:
            try:
                if resp.url in self.index:
                    continue
                ctype = (resp.headers or {}).get("content-type", "")
                self._save(resp.url, ctype, resp.body())
            except Exception as exc:  # redirect/streaming sem corpo
                self._fail(f"corpo {resp.url[:80]}", exc)

    def fetch_missing(self, request: Any, urls: List[str]) -> int:
        """Busca de novo as imagens da pagina que nao vieram pelo evento (ex.: cache do navegador)."""
        got = 0
        for url in dict.fromkeys(urls):
            if not url.startswith("http") or url in self.index:
                continue
            try:
                r = request.get(url, timeout=15_000)
                ctype = (r.headers or {}).get("content-type", "")
                if r.ok and _is_candidate(ctype):
                    before = len(self.index)
                    self._save(url, ctype, r.body())
                    got += len(self.index) - before
            except Exception as exc:
                self._fail(f"refetch {url[:80]}", exc)
        return got


def context_options(device: str, real_chrome_version: str = "") -> Dict[str, Any]:
    """Opcoes do contexto para o dispositivo.

    Com o Chrome real (CDP), o desktop NAO troca o User-Agent: um UA fixo "Chrome/131"
    num Chrome 14x contradiz os client hints (Sec-CH-UA) que o proprio navegador envia,
    e o Akamai da Magalu respondeu 403 na primeira requisicao (12/11/2026). No celular
    o UA precisa ser de Android, mas com a versao do Chrome que esta de fato rodando.
    """
    opts = dict(DEVICES[device], **CONTEXT_COMMON)
    major = (real_chrome_version or "").split(".")[0]
    if not major.isdigit():
        return opts
    if device == "desktop":
        opts.pop("user_agent", None)
    else:
        opts["user_agent"] = re.sub(r"Chrome/\d+", f"Chrome/{major}", opts["user_agent"])
    return opts


def _open_context(cfg: CaptureConfig):
    """Devolve (context, page, cleanup). Levanta RuntimeError se nao houver navegador."""
    if cfg.session not in SESSIONS:
        raise RuntimeError(f"sessao desconhecida: {cfg.session}")
    if cfg.session == "anon_warm" and (cfg.engine != "cdp" or cfg.device != "desktop"):
        raise RuntimeError("sessao anon_warm so existe no Chrome local (cdp) e em desktop")
    opts = dict(DEVICES[cfg.device], **CONTEXT_COMMON)
    if cfg.engine == "cdp":
        from shelfproof.browser.local_browser import get_local_browser

        lb = get_local_browser()
        if lb is None:
            raise RuntimeError(
                "Chrome local indisponivel. Ligue RAC_LOCAL_CHROME=1 e rode "
                "scripts\\start_chrome_cdp.bat (ou use --engine launch em site sem antibot)."
            )
        try:
            version = lb._browser.version
        except Exception:
            version = ""
        opts = context_options(cfg.device, version)
        if cfg.session == "anon_warm":
            # Sessao do perfil DEDICADO do Shelf Proof (nunca logado), aquecida na home como no
            # RAC: o Akamai da Magalu nega contexto novo e vazio (403 em 12/11/2026). So desktop:
            # o contexto ja existente nao troca UA/touch, entao nao ha celular de verdade aqui.
            page = lb.new_page()
            if page is None:
                raise RuntimeError("Aba nao abriu no Chrome local")
            page.set_viewport_size(DEVICES["desktop"]["viewport"])
            return lb.context, page, page.close
        if cfg.session == "anon":
            ctx = lb.new_isolated_context(**opts)
            if ctx is None:
                raise RuntimeError("Contexto isolado nao abriu no Chrome local")
            page = ctx.new_page()
            return ctx, page, ctx.close
        # persona: aba no perfil logado. Viewport ajustavel; UA/touch nao (limite do CDP compartilhado).
        page = lb.new_page()
        if page is None:
            raise RuntimeError("Aba nao abriu no Chrome local")
        page.set_viewport_size(DEVICES[cfg.device]["viewport"])
        return lb.context, page, page.close

    from shelfproof.browser import playwright_runtime

    pw, _flavor = playwright_runtime.acquire()
    if pw is None:
        raise RuntimeError("Playwright nao instalado (pip install playwright && playwright install chromium)")
    browser = pw.chromium.launch(headless=cfg.headless, channel="chrome")
    ctx = browser.new_context(**opts)
    page = ctx.new_page()

    def cleanup() -> None:
        try:
            ctx.close()
            browser.close()
        finally:
            playwright_runtime.release()

    return ctx, page, cleanup


def _human_scroll(page: Any, max_steps: int) -> int:
    """Rola ate o fim (lazy-load), com pausas humanas; volta ao topo. Devolve a altura final."""
    last_h, still = 0, 0
    for _ in range(max_steps):
        vh = page.evaluate("window.innerHeight")
        page.mouse.wheel(0, int(vh * random.uniform(0.7, 0.9)))
        time.sleep(random.uniform(0.6, 1.2))
        h = page.evaluate("document.documentElement.scrollHeight")
        at_end = page.evaluate("window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4")
        if at_end:
            still = still + 1 if h == last_h else 0
            if still >= 2:
                break
        last_h = h
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1.0)
    return int(page.evaluate("document.documentElement.scrollHeight"))


def _warm_up(page: Any, url: str) -> Dict[str, Any]:
    """Aquece a sessao na home do site (como o RAC): visita, mexe o mouse, rola e, em site
    com Akamai, espera o _abck validar. Devolve o que aconteceu, para o manifest."""
    from shelfproof.browser.local_browser import get_local_browser

    u = urlparse(url)
    home = f"{u.scheme}://{u.netloc}/"
    akamai = any(h in u.netloc for h in AKAMAI_HOSTS)
    lb = get_local_browser()
    ok = bool(lb) and lb.warmup(page, home, wait_abck=akamai, host_key=u.netloc)
    info: Dict[str, Any] = {"home": home, "akamai": akamai, "ok": bool(ok)}
    if akamai:
        try:
            ck = next((c["value"] for c in page.context.cookies(home) if c["name"] == "_abck"), "")
            info["abck"] = "validated" if "~0~" in ck else ("challenge" if ck else "absent")
        except Exception as exc:
            info["abck"] = f"erro: {exc}"
    time.sleep(random.uniform(2.0, 4.0))  # ritmo humano antes da captura
    return info


def _looks_blocked(page: Any, n_imgs: int, http_status: Optional[int] = None) -> Optional[str]:
    """Evidencia antes de string: so e bloqueio se NAO houver conteudo e houver sinal de bloqueio
    (frase de bloqueio/captcha, ou HTTP 403/429 na pagina principal)."""
    if n_imgs >= 8:
        return None
    if http_status in BLOCK_STATUS:
        return f"HTTP {http_status} na pagina principal"
    try:
        text = page.inner_text("body")[:5000]
    except Exception:
        text = ""
    m = BLOCK_PHRASES.search(text) or BLOCK_PHRASES.search(page.url)
    return m.group(0) if m else None


def capture(cfg: CaptureConfig) -> CaptureResult:
    """Executa uma captura. Nunca levanta por falha de artefato: registra em ``errors``."""
    t0 = now_brt()
    host_key = _slug(urlparse(cfg.url).netloc.replace("www.", ""))
    run_dir = cfg.out_root / t0.strftime("%Y-%m-%d") / f"{host_key}_{cfg.device}_{cfg.session}_{t0.strftime('%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    errors: List[str] = []
    manifest: Dict[str, Any] = {
        "url": cfg.url, "device": cfg.device, "session": cfg.session, "engine": cfg.engine,
        "collected_at": t0.isoformat(), "viewport": DEVICES[cfg.device]["viewport"],
    }
    sink = _ImageSink(run_dir / "images", cfg.min_image_bytes)
    marketplace = "generic"
    blocked = False

    try:
        ctx, page, cleanup = _open_context(cfg)
    except Exception as exc:  # sem navegador/sessao: a pasta ainda sai com o manifest e o motivo
        errors.append(f"contexto: {exc}")
        logger.error(f"[capture] {cfg.url} ({cfg.device}/{cfg.session}): {exc}")
        manifest.update(marketplace=marketplace, blocked=False, errors=errors, images_saved=0,
                        finished_at=now_brt().isoformat())
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return CaptureResult(run_dir=run_dir, marketplace=marketplace, ok=False, errors=errors)
    try:
        if cfg.session == "anon_warm":
            try:
                manifest["warmup"] = _warm_up(page, cfg.url)
                logger.info(f"[capture] aquecimento: {manifest['warmup']}")
            except Exception as exc:
                errors.append(f"aquecimento: {exc}")
        page.on("response", sink.on_response)
        logger.info(f"[capture] {cfg.url} ({cfg.device}/{cfg.session})")
        resp = page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
        http_status = resp.status if resp is not None else None
        manifest["http_status"] = http_status
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # home de marketplace raramente fica ociosa; seguir
        manifest["final_url"] = page.url

        # 1) carrossel: observar a 1a tela girando ANTES de rolar
        frames_dir = run_dir / "frames"
        frames_dir.mkdir(exist_ok=True)
        frames: List[Dict[str, Any]] = []
        n = max(1, int(cfg.carousel_seconds / cfg.carousel_interval))
        for k in range(n):
            try:
                f = frames_dir / f"frame_{k:02d}.jpg"
                page.screenshot(path=str(f), type="jpeg", quality=72)
                vis = [e for e in page.evaluate(ELEMENTS_JS)
                       if e["visible"] and e["y"] < DEVICES[cfg.device]["viewport"]["height"]]
                frames.append({"file": f.name, "t": round(k * cfg.carousel_interval, 1),
                               "visible_imgs": [e["src"] for e in vis]})
            except Exception as exc:
                errors.append(f"frame {k}: {exc}")
            time.sleep(cfg.carousel_interval)
        manifest["frames"] = frames

        # 2) rolar ate o fim para carregar o lazy-load
        try:
            manifest["page_height"] = _human_scroll(page, cfg.max_scroll_steps)
        except Exception as exc:
            errors.append(f"scroll: {exc}")

        # 3) artefatos, cada um no seu try
        html = ""
        try:
            html = page.content()
            (run_dir / "page.html").write_text(html, encoding="utf-8")
        except Exception as exc:
            errors.append(f"page.html: {exc}")
        elements: List[Dict[str, Any]] = []
        try:
            elements = page.evaluate(ELEMENTS_JS)
            (run_dir / "elements.json").write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:
            errors.append(f"elements.json: {exc}")
        try:
            page.screenshot(path=str(run_dir / "full.jpg"), full_page=True, type="jpeg", quality=70)
        except Exception as exc:
            errors.append(f"full.jpg: {exc}")

        marketplace = identify_marketplace(html, page.url)
        # 4) criativos: corpos das respostas anotadas + o que faltou, buscado pelo endereco
        try:
            sink.flush()
            visible_srcs = [e["src"] for e in elements if e.get("w", 0) >= 120 and e.get("h", 0) >= 60]
            refetched = sink.fetch_missing(ctx.request, visible_srcs)
            manifest["images_refetched"] = refetched
        except Exception as exc:
            errors.append(f"images: {exc}")

        reason = _looks_blocked(page, len(elements), http_status)
        if reason:
            blocked = True
            errors.append(f"BLOQUEIO: '{reason}' e so {len(elements)} imagens na pagina")
    except Exception as exc:
        errors.append(f"captura: {exc}")
        logger.error(f"[capture] falhou: {exc}")
    finally:
        if sink.failures:
            errors.append(f"imagens com falha (amostra): {sink.failures}")
        try:
            (run_dir / "images.json").write_text(json.dumps(sink.index, ensure_ascii=False, indent=0), encoding="utf-8")
        except Exception as exc:
            errors.append(f"images.json: {exc}")
        manifest.update(marketplace=marketplace, blocked=blocked, errors=errors,
                        images_saved=len(sink.index), finished_at=now_brt().isoformat())
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            cleanup()
        except Exception:
            pass

    if blocked:
        logger.error(f"[capture] BLOQUEADO em {cfg.url} ({cfg.device}): veja {run_dir / 'full.jpg'}")
    ok = (run_dir / "page.html").exists() and not blocked
    logger.info(f"[capture] {'OK' if ok else 'FALHOU'} -> {run_dir} ({len(sink.index)} imagens, {len(errors)} erros)")
    return CaptureResult(run_dir=run_dir, marketplace=marketplace, ok=ok, blocked=blocked, errors=errors)
