"""Fase 3: anunciante lido na IMAGEM quando o HTML nao diz quem pagou.

Casos reais do 11.11 (COMMON_MISTAKES S7): displays ``adplacements:*`` da Amazon,
parte do Mercado Ads e o Sponsored Brands da Neutrogena, cujo logo so existia
na peca grafica.

O que esta leitura PODE fazer:
  * dar nome a uma peca que o detector ja marcou como ``paid`` e deixou
    ``Nao identificado``, gravando em ``evidence`` o texto/logo que a sustenta;
  * dizer a marca em destaque de um banner da propria loja no varejo especialista
    (``extra.featured_brand`` vazio: sem marca no destino, no alt nem no arquivo).
    O banner continua da loja: a leitura nao o torna pago (24/11/2026).

O que ela NUNCA faz (regras duras 1 e 2 do CLAUDE.md):
  * transformar peca em paga: pago continua exigindo marcador no HTML;
  * trocar um anunciante que o HTML ja revelou;
  * aceitar palpite: sem marca visivel, ou confianca baixa, fica ``Nao identificado``
    (no banner da loja, fica sem marca em destaque).

Cada leitura fica em ``<run_dir>/vision.json`` (chave = sha256 da imagem), entao
reanalisar uma captura nao paga a API de novo e a leitura vira evidencia auditavel.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Protocol

from loguru import logger
from pydantic import BaseModel, Field

from shelfproof.detect.brands import find_brand
from shelfproof.detect.rules import MARKETPLACE_NAMES, SPECIALISTS
from shelfproof.models import UNKNOWN_ADVERTISER, Piece

DEFAULT_MODEL = "claude-opus-5-5"
ACCEPTED_CONFIDENCE = ("alta", "media")
API_MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}
MAX_SIDE = 1568  # acima disso a API reduz a imagem de qualquer jeito
MARKETPLACE_SELF = {"amazon", "mercado livre", "mercadolivre", "magalu", "magazine luiza",
                    "casas bahia", "shopee"}
# nome da propria loja especialista tambem nao e marca em destaque
SELF_NAMES = {n.lower() for _h, n, _c in SPECIALISTS.values()} | {k for k in SPECIALISTS} | \
             {"friopecas", "web continental", "climario", "central ar", "centralar.com", "ar certo"}

SYSTEM = """Voce audita pecas de midia paga (retail media) capturadas em home pages de \
marketplaces brasileiros. O detector ja provou pelo HTML que a peca e um espaco PAGO, mas o \
HTML nao diz quem pagou. Sua tarefa e dizer qual MARCA anunciante aparece na imagem.

Regras:
- So responda uma marca se ela estiver ESCRITA ou com o LOGOTIPO visivel na imagem. Leia; nao deduza.
- Nao deduza a marca pela categoria do produto, pela cor, pelo formato do aparelho ou pelo estilo.
- advertiser e a EMPRESA/MARCA dona, nao o nome do produto, modelo ou franquia
  ("iPhone 17" -> "Apple"; "Galaxy A57" -> "Samsung"; "Aspire Go" -> "Acer").
- Se aparecerem varias marcas, responda a que assina a peca (logo principal, chamada "na loja X",
  marca do produto em destaque). Marcas parceiras em selo (Intel Inside, Windows) nao assinam.
  Se duas empresas dividem a peca sem uma assinatura clara (ex.: jogo de uma editora sobre
  console de outra), brand_visible=false.
- O nome do proprio marketplace (Amazon, Mercado Livre, Magalu, Casas Bahia, Shopee) nao e o
  anunciante, a menos que a peca anuncie um produto de marca propria dele (ex.: Echo/Alexa, Kindle).
- text_seen: copie literalmente o texto ou descreva o logotipo que sustenta a resposta.
- confidence: "alta" = nome/logo legivel sem ambiguidade; "media" = legivel mas pequeno ou parcial;
  "baixa" = duvida real. Na duvida, "baixa".
- people_present: true se a peca mostra o rosto de uma pessoa real (modelo, artista, apresentador).
  Isso so alimenta a revisao humana de direitos de imagem; nao identifique quem e."""


SYSTEM_FEATURED = """Voce audita pecas da HOME de lojas brasileiras (marketplaces como Amazon, \
Mercado Livre, Magalu, Casas Bahia, Shopee, e o varejo especialista em ar-condicionado: Frigelar, \
Dufrio, Leveros...): banners, pop-ups, laterais, faixas. Estas pecas sao da PROPRIA LOJA, nao sao \
midia paga. O HTML nao diz qual marca a peca destaca. Sua tarefa e dizer qual MARCA de fabricante \
(Midea, LG, Samsung, Motorola, Electrolux, TCL, Daikin, Apple...) a peca destaca.

Regras:
- So responda uma marca se ela estiver ESCRITA ou com o LOGOTIPO visivel na imagem. Leia; nao deduza.
- Nao deduza a marca pelo formato do aparelho, pela cor, pela categoria ou pelo estilo.
- advertiser e a MARCA do fabricante, nao o modelo ("WindFree" -> "Samsung"; "BreezeIN" -> "TCL";
  "Dual Inverter" sem logo nao basta).
- O nome ou logo da propria loja (Amazon, Mercado Livre, Magalu, Casas Bahia, Shopee, Frigelar, Dufrio,
  Leveros, Poloar, Clima Rio, CentralAr, Denteck, ArCerto, Friopecas, WebContinental, Refricril) NAO e a
  marca em destaque, nem marca de cartao/banco/pagamento da loja (cartao Magalu, Mercado Pago).
- Peca de campanha da loja (Black Friday, cupom, frete, parcelamento, app) sem marca de fabricante
  escrita ou com logo: brand_visible=false.
- Varias marcas com o mesmo peso (ex.: "LG, Samsung e Midea com desconto"): brand_visible=false.
  So responda uma se ela assina ou domina a peca (logo principal, produto unico em destaque).
- text_seen: copie literalmente o texto ou descreva o logotipo que sustenta a resposta.
- confidence: "alta" = nome/logo legivel sem ambiguidade; "media" = legivel mas pequeno ou parcial;
  "baixa" = duvida real. Na duvida, "baixa".
- people_present: true se o banner mostra o rosto de uma pessoa real (modelo, artista, apresentador).
  Isso so alimenta a revisao humana de direitos de imagem; nao identifique quem e."""


class VisualReading(BaseModel):
    """Resposta estruturada da leitura visual de uma peca."""

    brand_visible: bool = Field(description="Ha marca anunciante escrita ou com logo visivel na peca")
    advertiser: str = Field(description="Nome da marca como aparece na peca; vazio se brand_visible=false")
    text_seen: str = Field(description="Texto literal ou descricao do logo que sustenta a resposta")
    confidence: Literal["alta", "media", "baixa"]
    people_present: bool = Field(description="A peca mostra rosto de pessoa real")


class VisionClient(Protocol):
    def read(self, image_bytes: bytes, media_type: str, context: str) -> Optional[VisualReading]: ...


@dataclass
class ClaudeVision:
    """Leitor via Claude API (visao + saida estruturada)."""

    model: str = DEFAULT_MODEL
    client: Any = None

    def __post_init__(self) -> None:
        if self.client is None:
            import anthropic  # import tardio: o projeto roda sem a dependencia quando a visao esta desligada

            self.client = anthropic.Anthropic()

    def read(self, image_bytes: bytes, media_type: str, context: str) -> Optional[VisualReading]:
        return self._read(SYSTEM, image_bytes, media_type, context)

    def read_featured(self, image_bytes: bytes, media_type: str, context: str) -> Optional[VisualReading]:
        """Marca em destaque num banner da propria loja (varejo especialista)."""
        return self._read(SYSTEM_FEATURED, image_bytes, media_type, context)

    def _read(self, system: str, image_bytes: bytes, media_type: str, context: str) -> Optional[VisualReading]:
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=system,
            # recusa do classificador de seguranca: o pedido e refeito em outro modelo, na mesma chamada
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                             "data": base64.standard_b64encode(image_bytes).decode("ascii")}},
                {"type": "text", "text": context},
            ]}],
            output_format=VisualReading,
        )
        if resp.stop_reason == "refusal":
            logger.warning(f"leitura visual recusada: {getattr(resp, 'stop_details', None)}")
            return None
        return resp.parsed_output


def _now_brt() -> str:
    return datetime.now(timezone(timedelta(hours=-3))).isoformat(timespec="seconds")


def prepare_image(path: Path) -> tuple[bytes, str]:
    """Bytes num formato que a API aceita (avif/bmp viram PNG; peca gigante e reduzida)."""
    from PIL import Image

    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as im:
        fmt = (im.format or "").upper()
        if fmt in API_MEDIA_TYPES and max(im.size) <= MAX_SIDE and len(raw) < 4_500_000:
            return raw, API_MEDIA_TYPES[fmt]
        im = im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") else im.convert("RGB")
        im.thumbnail((MAX_SIDE, MAX_SIDE))
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        return buf.getvalue(), "image/png"


def _context(p: Piece) -> str:
    parts = [f"Marketplace: {p.marketplace}", f"Formato: {p.ad_format}", f"Slot: {p.slot or '-'}"]
    if p.title:
        parts.append(f"Titulo no HTML: {p.title[:140]}")
    if p.alt and p.alt != p.title:
        parts.append(f"Alt no HTML: {p.alt[:140]}")
    parts.append("Qual marca anunciante aparece nesta peca?")
    return "\n".join(parts)


def accept(reading: VisualReading, marketplace: str) -> Optional[str]:
    """Nome canonico do anunciante, ou None quando a leitura nao basta como evidencia."""
    name = (reading.advertiser or "").strip()
    if not (reading.brand_visible and name and reading.confidence in ACCEPTED_CONFIDENCE):
        return None
    own = {marketplace.lower(), MARKETPLACE_NAMES.get(marketplace, "").lower(),
           MARKETPLACE_NAMES.get(marketplace, "").lower().replace("ç", "c")}
    if name.lower() in MARKETPLACE_SELF or name.lower() in own or name.lower() in SELF_NAMES:
        return None  # "a peca e da Amazon" / "o banner e da Frigelar" nao responde a marca
    return find_brand(name) or name


def _featured_context(p: Piece) -> str:
    parts = [f"Loja: {MARKETPLACE_NAMES.get(p.marketplace, p.marketplace)}", f"Slot: {p.slot or '-'}"]
    if p.alt:
        parts.append(f"Alt no HTML: {p.alt[:140]}")
    if p.href:
        parts.append(f"Destino do clique: {p.href[:160]}")
    if p.extra.get("zone"):
        parts.append(f"Onde aparece na pagina: {p.extra['zone']}")
    parts.append("Qual marca de fabricante esta peca da loja destaca?")
    return "\n".join(parts)


def is_featured_candidate(p: Piece, min_width: float = 300.0) -> bool:
    """Banner da loja sem marca em destaque, grande o bastante para ser vitrine: banner de
    especialista, ou peca que so a leitura da pagina viu (pop-up, meio da pagina, lateral...)."""
    from_reading = p.extra.get("found_by") == "leitura_da_pagina"
    vertical = p.bbox is not None and p.bbox.h >= 1.5 * p.bbox.w and p.bbox.w >= 100
    if from_reading and vertical:
        min_width = 100.0  # lateral/skyscraper e estreito por natureza
    return ((p.marketplace in SPECIALISTS or from_reading) and not p.is_paid and not p.extra.get("featured_brand")
            and not p.extra.get("logo_strip") and not p.extra.get("brands_seen")
            and not (p.bbox is not None and p.bbox.w < min_width))


def is_known_brand(name: str) -> bool:
    """A marca esta no dicionario (brands.py)? Fora dele, o nome lido precisa de conferencia humana."""
    return find_brand(name) == name


def _load_cache(run_dir: Path) -> Dict[str, Any]:
    try:
        return json.loads((run_dir / "vision.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_unknown_advertisers(pieces: List[Piece], run_dir: Path, reader: VisionClient,
                                model_label: str = "") -> Dict[str, int]:
    """Le na imagem o anunciante das pecas pagas sem nome. Altera ``pieces`` no lugar.

    Devolve contagens para log: candidatas, lidas (API), do cache, resolvidas, sem imagem, erros.
    """
    run_dir = Path(run_dir)
    cache = _load_cache(run_dir)
    stats = dict(candidates=0, api_calls=0, cached=0, resolved=0, needs_review=0, no_image=0, errors=0,
                 featured_candidates=0, featured_resolved=0)
    model_label = model_label or getattr(reader, "model", "") or "visao"
    featured_reader = getattr(reader, "read_featured", None)
    for p in pieces:
        featured = False
        if not (p.is_paid and p.advertiser == UNKNOWN_ADVERTISER):
            if featured_reader is None or not is_featured_candidate(p):
                continue
            featured = True
            stats["featured_candidates"] += 1
        else:
            stats["candidates"] += 1
        img_file = p.extra.get("image_file")
        path = run_dir / "images" / img_file if img_file else None
        if path is None or not path.exists():
            stats["no_image"] += 1
            continue
        try:
            data, media_type = prepare_image(path)
        except Exception as exc:  # imagem corrompida nao derruba as outras
            stats["errors"] += 1
            logger.warning(f"visao: nao abri {path.name}: {exc}")
            continue
        key = hashlib.sha256(data).hexdigest()
        if featured:  # outra pergunta (outro prompt) sobre a mesma imagem: outra entrada no cache
            key = "featured:" + key
        entry = cache.get(key)
        if entry is not None:
            stats["cached"] += 1
        else:
            try:
                reading = (featured_reader(data, media_type, _featured_context(p)) if featured
                           else reader.read(data, media_type, _context(p)))
            except Exception as exc:  # erro de API: a peca fica como estava, as outras seguem
                stats["errors"] += 1
                logger.warning(f"visao: falhou em {path.name}: {type(exc).__name__}: {exc}")
                continue
            stats["api_calls"] += 1
            entry = {"file": path.name, "model": model_label, "read_at": _now_brt(),
                     "reading": reading.model_dump() if reading else None}
            cache[key] = entry
        reading = VisualReading(**entry["reading"]) if entry.get("reading") else None
        if reading and reading.people_present:
            p.extra["people_present"] = "sim"
        name = accept(reading, p.marketplace) if reading else None
        if featured:
            if name:
                # o banner continua da loja (ownership intocado): so ganha a marca em destaque
                p.extra["featured_brand"] = name
                p.extra["featured_brand_source"] = "visao"
                if not is_known_brand(name):
                    p.extra["needs_review"] = "marca fora do dicionario: confirmar e incluir em brands.py"
                    stats["needs_review"] += 1
                p.evidence.append(f"marca em destaque: {name} (lida na imagem: '{reading.text_seen[:80]}', "
                                  f"{entry['model']}, confianca {reading.confidence})")
                stats["featured_resolved"] += 1
            elif reading:
                p.evidence.append(f"leitura visual sem marca em destaque confiavel (confianca {reading.confidence})")
            continue
        if name:
            p.advertiser = name
            p.extra["advertiser_source"] = "vision"
            if not is_known_brand(name):
                # nome novo (ou nome de produto em vez de empresa): vai para a revisao da folha de contato
                p.extra["needs_review"] = "marca fora do dicionario: confirmar e incluir em brands.py"
                stats["needs_review"] += 1
            p.evidence = [e for e in p.evidence if "precisa da leitura visual" not in e]
            p.evidence.append(f"anunciante lido na imagem: '{reading.text_seen[:80]}' "
                              f"({entry['model']}, confianca {reading.confidence})")
            stats["resolved"] += 1
        elif reading:
            p.evidence.append(f"leitura visual sem marca confiavel (confianca {reading.confidence})")
    try:
        (run_dir / "vision.json").write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as exc:
        logger.warning(f"visao: nao gravei vision.json: {exc}")
    return stats


def default_reader() -> Optional[VisionClient]:
    """Leitor padrao, ou None (com aviso) se faltar dependencia/credencial."""
    try:
        return ClaudeVision(model=os.getenv("SHELFPROOF_VISION_MODEL", DEFAULT_MODEL))
    except Exception as exc:
        logger.error(f"visao desligada: {exc} (pip install anthropic; ANTHROPIC_API_KEY no .env)")
        return None
