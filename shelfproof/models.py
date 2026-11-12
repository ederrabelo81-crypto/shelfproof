"""Modelo de dados do Shelf Proof.

Hierarquia de cinco niveis, igual para qualquer site, para que tudo seja
comparavel entre marketplaces, datas e dispositivos:

    Captura (pagina) > Zona > Slot > Peca > Item

Nesta primeira versao o detector produz ``Piece`` (peca) ja com o slot e a
posicao que a pagina declara. Zona e area visivel entram quando a captura
renderizada (``collect.capture``) fornecer as caixas dos elementos.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Literal, Optional

Ownership = Literal["paid", "marketplace", "brand_store", "organic"]
AdFormat = Literal[
    "banner",            # banner/carrossel com peca grafica
    "display",           # display vendido pela rede de ads do marketplace
    "sponsored_product",  # card de produto com rotulo de patrocinio
    "sponsored_brand",   # bloco de marca patrocinada (logo + produtos)
    "official_store",    # banner de loja oficial/parceira
    "shelf",             # vitrine (carrossel de produtos)
    "unknown",
]

UNKNOWN_ADVERTISER = "Nao identificado"


@dataclass
class BBox:
    """Caixa do elemento na pagina inteira (px CSS), vinda da captura renderizada."""

    x: float
    y: float
    w: float
    h: float
    viewport_h: float = 0.0

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.h)

    @property
    def fold(self) -> int:
        """1 = primeira tela, 2 = segunda... (0 quando a altura da tela e desconhecida)."""
        if not self.viewport_h:
            return 0
        return int(self.y // self.viewport_h) + 1


@dataclass
class Piece:
    """Uma peca vista na pagina: o criativo que ocupa um slot."""

    marketplace: str
    ownership: Ownership
    ad_format: AdFormat
    advertiser: str
    slot: str = ""
    position: Optional[int] = None
    title: str = ""
    alt: str = ""
    href: str = ""
    img_src: str = ""
    # Toda classificacao carrega o PORQUE. Sem evidencia, nao e "paid".
    evidence: List[str] = field(default_factory=list)
    bbox: Optional[BBox] = None
    extra: Dict[str, str] = field(default_factory=dict)

    @property
    def is_paid(self) -> bool:
        return self.ownership == "paid"

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.bbox is not None:
            d["bbox"]["area"] = self.bbox.area
            d["bbox"]["fold"] = self.bbox.fold
        return d
