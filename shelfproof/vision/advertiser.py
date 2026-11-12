"""Fase 3: anunciante lido na IMAGEM quando o HTML nao diz quem pagou.

Casos reais do 11.11 (COMMON_MISTAKES S7): displays ``adplacements:*`` da Amazon,
parte do Mercado Ads e o Sponsored Brands da Neutrogena, cujo logo so existia
na peca grafica.

O que esta leitura PODE fazer:
  * dar nome a uma peca que o detector ja marcou como ``paid`` e deixou
    ``Nao identificado``, gravando em ``evidence`` o texto/logo que a sustenta.

O que ela NUNCA faz (regras duras 1 e 2 do CLAUDE.md):
  * transformar peca em paga: pago continua exigindo marcador no HTML;
  * trocar um anunciante que o HTML ja revelou;
  * aceitar palpite: sem marca visivel, ou confianca baixa, fica ``Nao identificado``.

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
from shelfproof.models import UNKNOWN_ADVERTISER, Piece

DEFAULT_MODEL = "claude-opus-5-5"
ACCEPTED_CONFIDENCE = ("alta", "media")
API_MEDIA_TYPES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "GIF": "image/gif"}
MAX_SIDE = 1568  # acima disso a API reduz a imagem de qualquer jeito
MARKETPLACE_SELF = {"amazon", "mercado livre", "mercadolivre", "magalu", "magazine luiza",
                    "casas bahia", "shopee"}

SYSTEM = """Voce audita pecas de midia paga (retail media) capturadas em home pages de \
marketplaces brasileiros. O detector ja provou pelo HTML que a peca e um espaco PAGO, mas o \
HTML nao diz quem pagou. Sua tarefa e dizer qual MARCA anunciante aparece na imagem.

Regras:
- So responda uma marca se ela estiver ESCRITA ou com o LOGOTIPO visivel na imagem. Leia; nao deduza.
- Nao deduza a marca pela categoria do produto, pela cor, pelo formato do aparelho ou pelo estilo.
- Se aparecerem varias marcas, responda a que assina a peca (logo principal, chamada "na loja X",
  marca do produto em destaque). Se nenhuma assina claramente, brand_visible=false.
- O nome do proprio marketplace (Amazon, Mercado Livre, Magalu, Casas Bahia, Shopee) nao e o
  anunciante, a menos que a peca anuncie um produto de marca propria dele (ex.: Echo/Alexa, Kindle).
- text_seen: copie literalmente o texto ou descreva o logotipo que sustenta a resposta.
- confidence: "alta" = nome/logo legivel sem ambiguidade; "media" = legivel mas pequeno ou parcial;
  "baixa" = duvida real. Na duvida, "baixa".
- people_present: true se a peca mostra o rosto de uma pessoa real (modelo, artista, apresentador).
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
        resp = self.client.beta.messages.parse(
            model=self.model,
            max_tokens=4000,
            system=SYSTEM,
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
    if name.lower() in MARKETPLACE_SELF or name.lower() == marketplace.lower():
        return None  # "a peca e da Amazon" nao responde quem pagou
    return find_brand(name) or name


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
    stats = dict(candidates=0, api_calls=0, cached=0, resolved=0, no_image=0, errors=0)
    model_label = model_label or getattr(reader, "model", "") or "visao"
    for p in pieces:
        if not (p.is_paid and p.advertiser == UNKNOWN_ADVERTISER):
            continue
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
        entry = cache.get(key)
        if entry is not None:
            stats["cached"] += 1
        else:
            try:
                reading = reader.read(data, media_type, _context(p))
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
        if name:
            p.advertiser = name
            p.extra["advertiser_source"] = "vision"
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
