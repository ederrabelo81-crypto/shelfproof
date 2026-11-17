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
  // peca desenhada como fundo CSS dentro de link (ML 12/11/2026: cards de iPhone sem <img>)
  document.querySelectorAll('a, a *').forEach((el, i) => {
    const bg = getComputedStyle(el).backgroundImage || '';
    const m = bg.match(/url\(["']?(https?:[^"')]+)["']?\)/);
    if (!m) return;
    const r = el.getBoundingClientRect();
    if (r.width < 120 || r.height < 60) return;
    const a = el.closest('a');
    let op = 1, hidden = false;
    for (let n = el; n && n !== document.documentElement; n = n.parentElement) {
      const cs = getComputedStyle(n);
      op *= parseFloat(cs.opacity || '1');
      if (cs.visibility === 'hidden' || cs.display === 'none') { hidden = true; break; }
    }
    out.push({
      i: 100000 + i, src: m[1], alt: (el.innerText || '').trim().slice(0, 120),
      href: a ? a.href : '', x: r.left + sx, y: r.top + sy, w: r.width, h: r.height,
      nw: 0, nh: 0, visible: !hidden && op > 0.05, opacity: Math.round(op * 100) / 100,
      on_top: null, label: '', slot_id: '', background: true,
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
    mobile_emulation: str = ""         # celular anon_warm: full | no_lang | viewport ("" = variavel de ambiente ou full)


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
            c = ctype.split(";")[0].strip().lower()
            rtype = response.request.resource_type
            # octet-stream so de requisicao de imagem (fetch de API com CSP gerava falha falsa na Casas Bahia)
            if (c.startswith("image/") and "svg" not in c and rtype in ("image", "other", "fetch")) or \
                    (c in GENERIC_TYPES and rtype == "image"):
                self.pending.append(response)
        except Exception as exc:
            self._fail("resposta", exc)

    # Corpo que o navegador nunca guardou (pixel de metrica do ML, resposta de pagina que ja navegou):
    # nao e criativo perdido, entao nao conta como falha da captura
    _NOT_A_LOSS = ("No data found for resource", "navigated away from", "unavailable for redirect")

    def _fail(self, what: str, exc: Exception) -> None:
        if any(s in str(exc) for s in self._NOT_A_LOSS):
            return
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

    def flush(self, budget_s: float = 90.0) -> Dict[str, int]:
        """Le os corpos das respostas anotadas (fora do handler de eventos).

        ``response.body()`` nao tem tempo limite: numa resposta que nunca termina ele espera para
        sempre (Magalu desktop 17/11/2026: 17 min parado aqui). So le resposta ja terminada
        (``request.timing.responseEnd``) e para no prazo; o que ficou de fora e buscado de novo
        pelo endereco em ``fetch_missing()``, que tem tempo limite.
        """
        pending, self.pending = self.pending, []
        stats = {"read": 0, "unfinished": 0, "over_budget": 0}
        t0 = time.monotonic()
        for resp in pending:
            try:
                if resp.url in self.index:
                    continue
                if time.monotonic() - t0 > budget_s:
                    stats["over_budget"] += 1
                    continue
                timing = getattr(resp.request, "timing", None) or {}
                if timing and float(timing.get("responseEnd", 0) or 0) < 0:
                    stats["unfinished"] += 1
                    continue
                stats["read"] += 1
                ctype = (resp.headers or {}).get("content-type", "")
                self._save(resp.url, ctype, resp.body())
            except Exception as exc:  # redirect/streaming sem corpo
                self._fail(f"corpo {resp.url[:80]}", exc)
        return stats

    def fetch_missing(self, request: Any, urls: List[str], budget_s: float = 90.0) -> int:
        """Busca de novo as imagens da pagina que nao vieram pelo evento (ex.: cache do navegador)."""
        got = 0
        t0 = time.monotonic()
        for url in dict.fromkeys(urls):
            if not url.startswith("http") or url in self.index:
                continue
            if time.monotonic() - t0 > budget_s:
                self._fail("refetch", TimeoutError(f"prazo de {budget_s:.0f}s esgotado"))
                break
            try:
                r = request.get(url, timeout=10_000)
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


def mobile_ua_metadata(chrome_version: str) -> Dict[str, Any]:
    """Client hints de um Chrome Android com a MESMA versao do Chrome que esta rodando (S9)."""
    full = chrome_version if re.match(r"^\d+\.", chrome_version or "") else "131.0.0.0"
    major = full.split(".")[0]
    return {
        "brands": [{"brand": "Chromium", "version": major}, {"brand": "Google Chrome", "version": major},
                   {"brand": "Not_A Brand", "version": "24"}],
        "fullVersion": full, "platform": "Android", "platformVersion": "14.0.0",
        "architecture": "", "model": "Pixel 8", "mobile": True,
    }


MOBILE_EMULATION_MODES = ("full", "no_lang", "viewport")


def mobile_emulation_mode() -> str:
    """SHELFPROOF_MOBILE_EMULATION: full (UA + client hints + idioma), no_lang (UA + client hints,
    sem forcar idioma/plataforma, como o modo dispositivo do DevTools) ou viewport (so tela e toque;
    o navegador continua se apresentando como desktop). Teste A/B da Magalu celular, 17/11/2026."""
    import os

    m = (os.environ.get("SHELFPROOF_MOBILE_EMULATION") or "full").strip().lower()
    return m if m in MOBILE_EMULATION_MODES else "full"


def _emulation_mode(cfg: "CaptureConfig") -> str:
    """Modo do alvo (targets.json "mobile_emulation"); a variavel de ambiente vale para testes A/B."""
    import os

    if os.environ.get("SHELFPROOF_MOBILE_EMULATION"):
        return mobile_emulation_mode()
    m = (cfg.mobile_emulation or "").strip().lower()
    return m if m in MOBILE_EMULATION_MODES else "full"


def emulate_mobile_tab(page: Any, chrome_version: str = "", mode: str = "") -> Any:
    """Celular numa aba do perfil dedicado (anon_warm): tela, toque, UA e client hints pelo CDP.

    E o que o modo dispositivo do DevTools faz. Precisa vir ANTES do aquecimento e do goto:
    o Akamai le o UA no sensor e o _abck validado tem de ser o do celular.
    """
    mode = mode or mobile_emulation_mode()
    vp = DEVICES["mobile"]["viewport"]
    ua = context_options("mobile", chrome_version)["user_agent"]
    cdp = page.context.new_cdp_session(page)
    if mode == "full":
        cdp.send("Emulation.setUserAgentOverride", {
            "userAgent": ua, "acceptLanguage": "pt-BR,pt;q=0.9", "platform": "Linux armv8l",
            "userAgentMetadata": mobile_ua_metadata(chrome_version)})
    elif mode == "no_lang":
        cdp.send("Emulation.setUserAgentOverride", {
            "userAgent": ua, "userAgentMetadata": mobile_ua_metadata(chrome_version)})
    cdp.send("Emulation.setDeviceMetricsOverride", {
        "width": vp["width"], "height": vp["height"], "mobile": True,
        "deviceScaleFactor": DEVICES["mobile"]["device_scale_factor"]})
    cdp.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
    return cdp


def _open_context(cfg: CaptureConfig):
    """Devolve (context, page, cleanup). Levanta RuntimeError se nao houver navegador."""
    if cfg.session not in SESSIONS:
        raise RuntimeError(f"sessao desconhecida: {cfg.session}")
    if cfg.session == "anon_warm" and cfg.engine != "cdp":
        raise RuntimeError("sessao anon_warm so existe no Chrome local (cdp)")
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
            # RAC: o Akamai da Magalu nega contexto novo e vazio (403 em 12/11/2026).
            # Celular (17/11/2026): o contexto ja existente nao troca UA/touch pelo Playwright,
            # entao a ABA e emulada pelo CDP (o mesmo "modo dispositivo" do DevTools).
            page = lb.new_page()
            if page is None:
                raise RuntimeError("Aba nao abriu no Chrome local")
            if cfg.device == "mobile":
                # o celular deixa cookies de versao (m.<site>) que mandariam o DESKTOP para o site de
                # celular (Magalu 17/11/2026): guarda os cookies do site e devolve ao fechar a aba
                try:
                    snap = snapshot_site_cookies(lb.context, cfg.url)
                    cdp = emulate_mobile_tab(page, version, mode=_emulation_mode(cfg))
                except Exception:
                    page.close()
                    raise
                page._shelfproof_cdp = cdp  # mantem a sessao CDP (e a emulacao) viva com a aba

                def close_mobile() -> None:
                    try:
                        page.close()
                    finally:
                        try:
                            restore_site_cookies(lb.context, cfg.url, snap)
                        except Exception as exc:
                            logger.warning(f"[capture] cookies do site nao voltaram ao estado do desktop: {exc}")

                return lb.context, page, close_mobile
            else:
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


def _human_scroll(page: Any, max_steps: int, stats: Optional[Dict[str, int]] = None) -> int:
    """Rola ate o fim (lazy-load), com pausas humanas; volta ao topo. Devolve a altura final.

    Se a roda do mouse nao mexer a pagina (celular emulado, ou o cursor parado sobre um iframe
    que engole a rolagem: Magalu celular 17/11/2026 parou em 1962 px com as vitrines vazias),
    rola por script, do mesmo tamanho. ``stats["script_scrolls"]`` conta quantas vezes.
    """
    last_h, still = 0, 0
    if stats is not None:
        stats.setdefault("script_scrolls", 0)
    for _ in range(max_steps):
        vh = page.evaluate("window.innerHeight")
        dy = int(vh * random.uniform(0.7, 0.9))
        y0 = page.evaluate("window.scrollY")
        page.mouse.wheel(0, dy)
        time.sleep(random.uniform(0.6, 1.2))
        if page.evaluate("window.scrollY") == y0 and not page.evaluate(
                "window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4"):
            page.evaluate(f"window.scrollBy(0, {dy})")
            time.sleep(random.uniform(0.6, 1.2))
            if stats is not None:
                stats["script_scrolls"] += 1
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


def _site_domain(url: str) -> str:
    """magazineluiza.com.br para www./m.magazineluiza.com.br."""
    host = urlparse(url).netloc.lower().split(":")[0]
    return re.sub(r"^(www|m)\.", "", host)


def _is_mobile_site(final_url: str, asked_url: str) -> bool:
    """O site mandou para a versao de celular (m.<dominio>) sem a gente ter pedido."""
    fh, ah = urlparse(final_url).netloc.lower(), urlparse(asked_url).netloc.lower()
    return fh.startswith("m.") and not ah.startswith("m.")


def _cookie_matches(c: Dict[str, Any], base: str) -> bool:
    d = (c.get("domain") or "").lstrip(".").lower()
    return d == base or d.endswith("." + base)


def _clear_site_cookies(context: Any, url: str) -> int:
    """Apaga os cookies do site (perfil dedicado, nunca logado). Devolve quantos."""
    base = _site_domain(url)
    n = sum(1 for c in context.cookies() if _cookie_matches(c, base))
    context.clear_cookies(domain=re.compile(r"(^|\.)" + re.escape(base) + r"$"))
    _forget_warm(url)
    return n


_COOKIE_KEYS = ("name", "value", "domain", "path", "expires", "httpOnly", "secure", "sameSite")


def snapshot_site_cookies(context: Any, url: str) -> List[Dict[str, Any]]:
    base = _site_domain(url)
    out = []
    for c in context.cookies():
        if _cookie_matches(c, base):
            k = {key: c[key] for key in _COOKIE_KEYS if key in c}
            if k.get("expires", 0) is not None and float(k.get("expires", 0)) < 0:
                k.pop("expires", None)  # cookie de sessao
            out.append(k)
    return out


def restore_site_cookies(context: Any, url: str, snap: List[Dict[str, Any]]) -> None:
    """Volta os cookies do site ao que eram antes do celular (o desktop nao herda a versao m.)."""
    base = _site_domain(url)
    context.clear_cookies(domain=re.compile(r"(^|\.)" + re.escape(base) + r"$"))
    if snap:
        context.add_cookies(snap)
    _forget_warm(url, devices=("mobile",))


def _forget_warm(url: str, devices: tuple = ("desktop", "mobile")) -> None:
    """Esquece que o site foi aquecido (o proximo uso aquece de novo)."""
    try:
        from shelfproof.browser.local_browser import get_local_browser

        lb = get_local_browser()
        host = urlparse(url).netloc
        for d in devices:
            lb._warmed_hosts.discard(f"{host}#{d}")
    except Exception:
        pass


def _warm_up(page: Any, url: str, device: str = "desktop", force: bool = False) -> Dict[str, Any]:
    """Aquece a sessao na home do site (como o RAC): visita, mexe o mouse, rola e, em site
    com Akamai, espera o _abck validar. Devolve o que aconteceu, para o manifest."""
    from shelfproof.browser.local_browser import get_local_browser

    u = urlparse(url)
    home = f"{u.scheme}://{u.netloc}/"
    akamai = any(h in u.netloc for h in AKAMAI_HOSTS)
    lb = get_local_browser()
    if force:
        _forget_warm(url, (device,))
    # o celular aquece de novo: o _abck validado com o UA do desktop nao vale para o do celular
    ok = bool(lb) and lb.warmup(page, home, wait_abck=akamai, host_key=f"{u.netloc}#{device}")
    info: Dict[str, Any] = {"home": home, "akamai": akamai, "ok": bool(ok), "device": device}
    if akamai:
        try:
            ck = next((c["value"] for c in page.context.cookies(home) if c["name"] == "_abck"), "")
            info["abck"] = "validated" if "~0~" in ck else ("challenge" if ck else "absent")
        except Exception as exc:
            info["abck"] = f"erro: {exc}"
    time.sleep(random.uniform(2.0, 4.0))  # ritmo humano antes da captura
    return info


# Botoes que um cliente clicaria para ver a vitrine. So nomes EXATOS: nunca login, nunca captcha.
OVERLAY_BUTTONS = [
    re.compile(r"^\s*portugu[eê]s\s*\(br\)\s*$", re.I),            # Shopee: "Selecione seu idioma"
    re.compile(r"^\s*aceitar( todos)?( os)?( cookies)?\s*$", re.I),  # aviso de cookies
    re.compile(r"^\s*(aceito|concordo|entendi|ok,? entendi)\s*$", re.I),
    # pesquisa de satisfacao (Magalu celular 17/11/2026: QuestionPro "Queremos o seu feedback",
    # dentro de um iframe). Recusar a pesquisa e o que o cliente faz para ver a vitrine.
    re.compile(r"^\s*(agora n[aã]o|n[aã]o,? obrigad[oa])\s*$", re.I),
]


# Opcoes de idioma que nao sao <button> (Shopee 12/11/2026: o seletor nao tem papel de botao).
# Clique por TEXTO exato so aqui: nome de idioma nao se confunde com login nem captcha.
# So com a janela "Selecione seu idioma" aberta, e na opcao mais baixa da tela: o mesmo texto existe
# no seletor de idioma do cabecalho, que nao deve ser clicado.
OVERLAY_TEXTS = [re.compile(r"^\s*portugu[eê]s\s*\(br\)\s*$", re.I)]
LANGUAGE_DIALOG = re.compile(r"selecione seu idioma", re.I)


def _click_language_option(page: Any, pat: Any) -> str:
    """Clica a opcao de idioma DENTRO da janela de escolha (a mais baixa entre as visiveis)."""
    if not page.get_by_text(LANGUAGE_DIALOG).first.is_visible():
        return ""
    loc = page.get_by_text(pat)
    best, best_y = None, -1.0
    for i in range(min(loc.count(), 5)):
        b = loc.nth(i)
        box = b.bounding_box() if b.is_visible() else None
        if box and box["y"] > best_y:
            best, best_y = b, box["y"]
    if best is None:
        return ""
    name = (best.inner_text(timeout=1000) or "").strip()
    best.click(timeout=2000)
    return name


def dismiss_overlays(page: Any, passes: int = 2) -> List[str]:
    """Fecha janelas que cobrem a vitrine (idioma, cookies, pesquisa). Devolve o que foi clicado.

    Botoes sao procurados tambem dentro de iframes: a pesquisa da Magalu no celular (QuestionPro)
    e um iframe por cima da home, e o "Agora nao" nao aparece para a pagina principal.
    """
    clicked: List[str] = []
    for _ in range(passes):
        hit = False
        targets = [("button", p) for p in OVERLAY_BUTTONS] + [("text", p) for p in OVERLAY_TEXTS]
        for kind, pat in targets:
            try:
                if kind == "text":
                    name = _click_language_option(page, pat)
                    if name:
                        clicked.append(name)
                        hit = True
                        time.sleep(random.uniform(0.6, 1.2))
                    continue
                for j, fr in enumerate(_frames(page)):
                    loc = fr.get_by_role("button", name=pat)
                    if j > 0 and loc.count() == 0:
                        # dentro da janela o "botao" pode ser um div clicavel: texto EXATO, so no iframe
                        loc = fr.get_by_text(pat)
                    done = False
                    for i in range(min(loc.count(), 3)):
                        b = loc.nth(i)
                        if b.is_visible():
                            name = (b.inner_text(timeout=1000) or "").strip()
                            b.click(timeout=2000)
                            clicked.append(name)
                            hit = done = True
                            time.sleep(random.uniform(0.6, 1.2))
                            break
                    if done:
                        break
            except Exception:
                continue  # botao sumiu entre a contagem e o clique: segue
        if not hit:
            break
        time.sleep(1.0)  # a proxima janela pode aparecer depois da primeira
    return clicked


def _frames(page: Any) -> List[Any]:
    """A pagina e os iframes que podem ser uma janela por cima dela: grandes e na tela.

    Nunca todos os iframes: pagina de marketplace tem dezenas (anuncios, rastreio), e consultar
    um iframe que nao terminou de carregar pode demorar.
    """
    out: List[Any] = []
    try:
        out.append(page.main_frame)
        vp = page.viewport_size or {"width": 1440, "height": 900}
        for h in page.query_selector_all("iframe")[:40]:
            box = h.bounding_box()
            if not box or box["width"] < 200 or box["height"] < 120:
                continue
            if box["y"] > vp["height"] or box["y"] + box["height"] < 0:
                continue
            fr = h.content_frame()
            if fr is not None:
                out.append(fr)
    except Exception:
        pass
    return out or [page]


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
    # segundos gastos em cada etapa; "stage" = a ultima iniciada (se a captura for interrompida
    # com Ctrl+C, o manifest diz onde parou)
    timings: Dict[str, float] = {}
    manifest["timings"] = timings
    clock = {"name": "open", "t": time.monotonic()}

    def stage(name: str) -> None:
        now = time.monotonic()
        timings[clock["name"]] = round(timings.get(clock["name"], 0) + now - clock["t"], 1)
        clock.update(name=name, t=now)
        manifest["stage"] = name

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
                if cfg.device == "mobile":
                    # celular emulado na aba do perfil dedicado; o modo vai junto (viewport = UA de desktop)
                    manifest["emulation"] = f"cdp_tab:{_emulation_mode(cfg)}"
                stage("warmup")
                manifest["warmup"] = _warm_up(page, cfg.url, cfg.device)
                logger.info(f"[capture] aquecimento: {manifest['warmup']}")
            except Exception as exc:
                errors.append(f"aquecimento: {exc}")
        page.on("response", sink.on_response)
        http_errors: List[str] = []
        manifest["http_errors"] = http_errors

        def _on_err(r: Any) -> None:  # chamadas recusadas pelo site (vitrine vazia sem motivo aparente)
            try:
                if r.status >= 400 and len(http_errors) < 30 and \
                        r.request.resource_type in ("document", "xhr", "fetch", "script"):
                    u = urlparse(r.url)
                    http_errors.append(f"{r.status} {r.request.resource_type} {u.netloc}{u.path[:80]}")
            except Exception:
                pass

        page.on("response", _on_err)
        # diagnostico da vitrine vazia (Magalu celular 17/11/2026: caixas lazyload nunca preenchidas,
        # sem nenhuma chamada recusada): erros de JavaScript e as chamadas de conteudo que a pagina fez
        js_errors: List[str] = []
        api_calls: List[str] = []
        manifest["js_errors"] = js_errors
        manifest["api_calls"] = api_calls

        def _on_pageerror(e: Any) -> None:
            if len(js_errors) < 15:
                js_errors.append(f"pageerror: {str(e)[:400]}")

        def _on_console(m: Any) -> None:
            try:
                if m.type == "error" and len(js_errors) < 15:
                    js_errors.append(f"console: {m.text[:400]}")
            except Exception:
                pass

        def _on_api(r: Any) -> None:
            try:
                if r.request.resource_type in ("xhr", "fetch") and len(api_calls) < 60:
                    u = urlparse(r.url)
                    api_calls.append(f"{r.status} {u.netloc}{u.path[:90]}")
            except Exception:
                pass

        # CORS: o Playwright nao mostra a resposta do preflight. Pelo CDP da aba: o tipo exato do erro
        # (corsErrorStatus) e o Access-Control-Allow-Origin que o servidor devolveu (Magalu celular 17/11)
        cors: List[Dict[str, Any]] = []
        manifest["cors_errors"] = cors
        try:
            net = getattr(page, "_shelfproof_cdp", None) or page.context.new_cdp_session(page)
            page._shelfproof_net = net
            req_info: Dict[str, Dict[str, Any]] = {}
            net.send("Network.enable")

            def _will(ev: Dict[str, Any]) -> None:
                if len(req_info) < 3000:
                    req_info[ev.get("requestId", "")] = {"url": ev.get("request", {}).get("url", "")[:160],
                                                         "method": ev.get("request", {}).get("method", "")}

            def _resp(ev: Dict[str, Any]) -> None:
                r = ev.get("response", {})
                info = req_info.get(ev.get("requestId", ""))
                if info is not None:
                    h = {k.lower(): v for k, v in (r.get("headers") or {}).items()}
                    info.update(status=r.get("status"), acao=h.get("access-control-allow-origin"),
                                acac=h.get("access-control-allow-credentials"), vary=h.get("vary"))

            def _failed(ev: Dict[str, Any]) -> None:
                st = ev.get("corsErrorStatus")
                if st and len(cors) < 15:
                    info = dict(req_info.get(ev.get("requestId", ""), {}))
                    cors.append(dict(info, cors_error=st.get("corsError"), failed_parameter=st.get("failedParameter"),
                                     error=ev.get("errorText")))

            net.on("Network.requestWillBeSent", _will)
            net.on("Network.responseReceived", _resp)
            net.on("Network.loadingFailed", _failed)
        except Exception as exc:
            manifest["cors_errors_unavailable"] = str(exc)[:200]
        page.on("pageerror", _on_pageerror)
        page.on("console", _on_console)
        page.on("response", _on_api)
        logger.info(f"[capture] {cfg.url} ({cfg.device}/{cfg.session})")
        stage("goto")
        resp = page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
        http_status = resp.status if resp is not None else None
        manifest["http_status"] = http_status
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass  # home de marketplace raramente fica ociosa; seguir
        manifest["final_url"] = page.url
        if cfg.session == "anon_warm" and cfg.device == "desktop" and _is_mobile_site(page.url, cfg.url):
            # 17/11/2026: depois do celular no mesmo perfil, a Magalu mandou o DESKTOP para m.magazineluiza
            # (cookie de versao). Limpa os cookies do site, aquece de novo como desktop e tenta outra vez.
            logger.warning(f"[capture] desktop caiu no site de celular ({page.url}): limpando cookies do site")
            stage("redirect_fix")
            manifest["mobile_redirect_fixed"] = _clear_site_cookies(page.context, cfg.url)
            try:
                manifest["warmup_retry"] = _warm_up(page, cfg.url, cfg.device, force=True)
                resp = page.goto(cfg.url, wait_until="domcontentloaded", timeout=60_000)
                http_status = resp.status if resp is not None else None
                manifest["http_status"] = http_status
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:
                    pass
            except Exception as exc:
                errors.append(f"redirect_fix: {exc}")
            manifest["final_url"] = page.url
            if _is_mobile_site(page.url, cfg.url):
                errors.append(f"desktop redirecionado para o site de celular: {page.url}")

        stage("overlays")
        # 0) janelas por cima da vitrine (idioma da Shopee, aviso de cookies): fechar como um cliente
        try:
            manifest["dismissed"] = dismiss_overlays(page)
        except Exception as exc:
            errors.append(f"overlays: {exc}")

        stage("frames")
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

        stage("scroll")
        # 2) rolar ate o fim para carregar o lazy-load. Antes, fechar de novo: janela que carrega
        # por ultimo (pesquisa da Magalu, lazyOnload) aparece depois da 1a tentativa.
        try:
            manifest["dismissed"] = manifest.get("dismissed", []) + dismiss_overlays(page)
        except Exception as exc:
            errors.append(f"overlays: {exc}")
        try:
            st: Dict[str, int] = {}
            manifest["page_height"] = _human_scroll(page, cfg.max_scroll_steps, st)
            manifest["script_scrolls"] = st.get("script_scrolls", 0)
        except Exception as exc:
            errors.append(f"scroll: {exc}")

        stage("artifacts")
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
        stage("images")
        # 4) criativos: corpos das respostas anotadas + o que faltou, buscado pelo endereco
        try:
            manifest["image_bodies"] = sink.flush()
            stage("refetch")
            visible_srcs = [e["src"] for e in elements if e.get("w", 0) >= 120 and e.get("h", 0) >= 60]
            refetched = sink.fetch_missing(ctx.request, visible_srcs)
            manifest["images_refetched"] = refetched
        except Exception as exc:
            errors.append(f"images: {exc}")

        stage("done")
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
        stage("end")
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
