"""Detector de pecas e de propriedade do espaco (pago / marketplace / loja da marca).

Uma funcao por marketplace, porque cada um expoe o inventario de midia de um
jeito. Regras levantadas nas homes de 11/11/2026 (docs/MAPA_SLOTS.md):

* Magalu      alt "Abrir oferta patrocinada - slot <id>, posicao <n>" + link /selecao/<slug>
* Casas Bahia parametro vtr_name=Ads_CB_<data>_<Marca>_<device> no link do banner
* Amazon      rotulo "Patrocinado" no card + placements "adplacements:*" (data-csa-c-slot-id)
* Mercado Livre peca de display (click1.../display/clicks) com "_ADS_" no codigo do alt
* Shopee      adsTrackingPayload no link; banners de "Lojas Oficiais" no carrossel
* Loja da marca (dominio da propria marca) tudo e brand_store

REGRA DURA (herdada do RAC, COMMON_MISTAKES #15 e #20): evidencia antes de
string, e ausencia de dado e dado ausente. Toda peca "paid" carrega em
``evidence`` o marcador que a justificou; sem marcador, nao e paga. Anunciante
que o HTML nao revela fica ``Nao identificado`` -- nunca chutado.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup, Tag

from shelfproof.detect.brands import find_brand, find_brand_first
from shelfproof.models import UNKNOWN_ADVERTISER, Piece

SPONSOR_LABEL_RE = re.compile(r"^\s*(patrocinad[oa]s?|publicidade|an[uú]ncio|sponsored)\s*$", re.I)

MARKETPLACE_HOSTS: Dict[str, str] = {
    "amazon.com.br": "amazon",
    "mercadolivre.com.br": "mercadolivre",
    "magazineluiza.com.br": "magalu",
    "casasbahia.com.br": "casasbahia",
    "shopee.com.br": "shopee",
    "midea.com.br": "midea",
}
MARKETPLACE_NAMES: Dict[str, str] = {
    "amazon": "Amazon",
    "mercadolivre": "Mercado Livre",
    "magalu": "Magalu",
    "casasbahia": "Casas Bahia",
    "shopee": "Shopee",
    "midea": "Loja Midea",
    "generic": "Site",
}
# Lojas da propria marca: tudo que aparece la e da marca (brand_store).
BRAND_STORES: Dict[str, str] = {"midea": "Midea"}


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def identify_marketplace(html: str, url: str = "") -> str:
    """Pelo host da URL; sem URL, pelo canonical/og:url/titulo da pagina salva."""
    host = urlparse(url).netloc.lower() if url else ""
    if not host:
        m = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html[:300000], re.I) or \
            re.search(r'property="og:url"[^>]+content="([^"]+)"', html[:300000], re.I)
        host = urlparse(m.group(1)).netloc.lower() if m else ""
    for h, key in MARKETPLACE_HOSTS.items():
        if host.endswith(h):
            return key
    head = html[:20000].lower()
    for key, needle in [("amazon", "amazon.com.br"), ("mercadolivre", "mercado livre"),
                        ("magalu", "magalu"), ("casasbahia", "casas bahia"),
                        ("shopee", "shopee"), ("midea", "midea")]:
        if needle in head:
            return key
    return "generic"


def img_src(img: Tag) -> str:
    for attr in ("src", "data-src", "data-lazy-src", "data-original"):
        v = img.get(attr)
        if v and not v.startswith("data:"):
            return v
    srcset = img.get("srcset") or img.get("data-srcset") or ""
    if srcset:
        return srcset.split(",")[0].strip().split(" ")[0]
    return img.get("src") or ""


def parent_href(node: Tag) -> str:
    a = node if node.name == "a" else node.find_parent("a")
    return (a.get("href") or "") if a else ""


def _clean(s: Optional[str], n: int = 160) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:n]


def _dedupe(pieces: Iterable[Piece]) -> List[Piece]:
    seen, out = set(), []
    for p in pieces:
        if p.ad_format in ("sponsored_product", "sponsored_brand"):
            # o mesmo produto patrocinado em duas vitrines = duas posicoes compradas
            out.append(p)
            continue
        # carrossel clona a primeira/ultima peca: mesmo destino + mesmo slot = mesma peca
        key = (p.ownership, p.slot, p.href or p.img_src or p.title, p.advertiser)
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Magalu
# ---------------------------------------------------------------------------
_MAGALU_SLOT_RE = re.compile(r"slot\s+([\w\-]+),\s*posi[cç][aã]o\s+(\d+)", re.I)
_MAGALU_OWN_SLUGS = re.compile(r"antecipad|montagem|telefonia|entregarapida|entrega|magaluempresas|cupom|frete|black", re.I)


def _magalu(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for img in soup.find_all("img"):
        alt = _clean(img.get("alt"), 300)
        href = parent_href(img)
        m = _MAGALU_SLOT_RE.search(alt)
        slug = ""
        sm = re.search(r"/selecao/([^/?#]+)", href)
        if sm:
            slug = sm.group(1)
        if m:
            slot, pos = m.group(1), int(m.group(2))
            brand = find_brand(slug, href) if (slug or href) else None
            if "magaluempresas" in href:
                brand = None
            if brand:
                out.append(Piece("magalu", "paid", "banner", brand, slot, pos, title=slug, alt=alt, href=href,
                                 img_src=img_src(img),
                                 evidence=[f"alt declara slot patrocinado '{slot}' posicao {pos}",
                                           f"destino /selecao/{slug} contem a marca {brand}"]))
            else:
                out.append(Piece("magalu", "marketplace", "banner", "Magalu", slot, pos, title=slug or href,
                                 alt=alt, href=href, img_src=img_src(img),
                                 evidence=[f"slot '{slot}' sem marca no destino ({slug or href[:60]}): campanha do proprio Magalu"]))
        elif alt.lower().startswith("banner de ofertas") and slug:
            brand = find_brand(slug)
            if brand and not _MAGALU_OWN_SLUGS.search(slug):
                out.append(Piece("magalu", "paid", "banner", brand, "banner lateral", None, title=slug, alt=alt,
                                 href=href, img_src=img_src(img),
                                 evidence=[f"banner lateral com destino /selecao/{slug} (marca {brand})"]))
    # vitrine "Patrocinados": cards de produto abaixo do titulo
    for lab in soup.find_all(string=re.compile(r"^\s*Patrocinados\s*$")):
        box = lab.parent
        for _ in range(6):
            if box.parent is None:
                break
            box = box.parent
            if len(box.find_all("a", href=re.compile(r"/p/"))) >= 1:
                break
        for a in box.find_all("a", href=re.compile(r"/p/"))[:12]:
            title = _clean(a.get("title") or a.get_text(" "), 140)
            if not title:
                continue
            card_img = a.find("img")
            out.append(Piece("magalu", "paid", "sponsored_product", find_brand_first(title) or UNKNOWN_ADVERTISER,
                             "vitrine Patrocinados", None, title=title, href=a.get("href", ""),
                             img_src=img_src(card_img) if card_img else "",
                             evidence=["card dentro da vitrine com rotulo 'Patrocinados'"]))
    return out


# ---------------------------------------------------------------------------
# Casas Bahia
# ---------------------------------------------------------------------------
def _casasbahia(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for a in soup.find_all("a", href=re.compile(r"vtr_name=")):
        href = a.get("href", "")
        vtr = unquote((parse_qs(urlparse(href).query).get("vtr_name") or [""])[0]).replace("+", " ")
        img = a.find("img")
        alt = _clean(img.get("alt") if img else a.get_text(" "), 300)
        src = img_src(img) if img else ""
        if re.match(r"\s*Ads_CB", vtr, re.I):
            parts = [p for p in re.split(r"[_\s]+", vtr) if p]
            brand = find_brand(" ".join(parts[2:]), alt) or UNKNOWN_ADVERTISER
            out.append(Piece("casasbahia", "paid", "banner", brand, vtr, 1, title=alt, alt=alt, href=href, img_src=src,
                             evidence=[f"vtr_name '{vtr}' (prefixo Ads_CB = midia vendida)"]))
        else:
            out.append(Piece("casasbahia", "marketplace", "banner", "Casas Bahia", vtr, 1, title=alt, alt=alt,
                             href=href, img_src=src, evidence=[f"vtr_name '{vtr}' sem prefixo Ads_CB"],
                             extra={"featured_brand": find_brand(alt) or ""}))
    return out


# ---------------------------------------------------------------------------
# Amazon
# ---------------------------------------------------------------------------
def _amazon(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for div in soup.find_all(attrs={"data-csa-c-slot-id": re.compile(r"^adplacements:")}):
        sid = div.get("data-csa-c-slot-id", "")
        out.append(Piece("amazon", "paid", "display", UNKNOWN_ADVERTISER, sid.split(":")[2] if sid.count(":") >= 2 else sid,
                         None, title="Display Amazon Ads", evidence=[f"data-csa-c-slot-id '{sid}'"]))
    for lab in soup.find_all(string=SPONSOR_LABEL_RE):
        card: Optional[Tag] = lab.parent
        links: List[str] = []
        for _ in range(12):
            if card is None or card.parent is None:
                break
            card = card.parent
            links = [x.get("href", "") for x in card.find_all("a") if x.get("href")]
            if links:
                break
        if card is None:
            continue
        img = card.find("img")
        alt = _clean(img.get("alt") if img else "", 200)
        text = _clean(card.get_text(" "), 200)
        href = links[0] if links else ""
        slug = ""
        mm = re.search(r"amazon\.com\.br/([^/]+)/dp/", href)
        if mm:
            slug = unquote(mm.group(1)).replace("-", " ")
        is_brand_block = alt == "Imagem com a marca" or "aax-" in href
        headline = re.sub(r"\s*Patrocinad[oa]s?\s*$", "", text, flags=re.I)
        brand = find_brand(slug, alt if alt not in ("Imagem do produto", "Imagem com a marca") else "", headline)
        title = alt if alt and not alt.startswith("Imagem ") else (slug or headline)
        out.append(Piece("amazon", "paid", "sponsored_brand" if is_brand_block else "sponsored_product",
                         brand or UNKNOWN_ADVERTISER, "Sponsored Brands" if is_brand_block else "Sponsored Products",
                         None, title=_clean(title, 140), alt=alt, href=href, img_src=img_src(img) if img else "",
                         evidence=["rotulo 'Patrocinado' no card"] +
                                  ([f"marca lida em '{(slug or headline)[:60]}'"] if brand else
                                   ["anunciante so aparece na imagem: precisa da leitura visual"])))
    # banners da propria Amazon (gateway / hero) com alt descritivo
    for img in soup.find_all("img"):
        src = img_src(img)
        alt = _clean(img.get("alt"), 200)
        if re.search(r"_SF1282|_SR428,684|DossierVisualNav_1111", src) and alt and alt != "Imagem com a marca":
            out.append(Piece("amazon", "marketplace", "banner", "Amazon", "gateway", None, title=alt, alt=alt,
                             href=parent_href(img), img_src=src, evidence=["peca do gateway/hero sem rotulo de patrocinio"]))
    return out


# ---------------------------------------------------------------------------
# Mercado Livre
# ---------------------------------------------------------------------------
def _mercadolivre(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for img in soup.find_all("img"):
        href = parent_href(img)
        alt = _clean(img.get("alt"), 200)
        if "click1.mercadolivre.com.br/display/clicks" not in href and "bannermenu" not in href:
            continue
        if not alt:
            continue
        if "_ADS_" in alt.upper():
            code = alt
            brand = find_brand(code.replace("_", " ")) or UNKNOWN_ADVERTISER
            out.append(Piece("mercadolivre", "paid", "display", brand, code, 1, title=code, alt=alt, href=href,
                             img_src=img_src(img), evidence=[f"codigo da peca '{code}' contem _ADS_ (Mercado Ads)"]))
        else:
            out.append(Piece("mercadolivre", "marketplace", "banner", "Mercado Livre",
                             alt if alt.startswith("MS_") else "display", 1, title=alt, alt=alt, href=href,
                             img_src=img_src(img), evidence=["peca de display sem codigo _ADS_"]))
    return out


# ---------------------------------------------------------------------------
# Shopee
# ---------------------------------------------------------------------------
def _shopee(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for img in soup.find_all("img"):
        href = parent_href(img)
        alt = _clean(img.get("alt"), 240)
        if "adsTrackingPayload" in href:
            sid = re.search(r"/shop/(\d+)", href)
            out.append(Piece("shopee", "paid", "official_store", find_brand(alt) or UNKNOWN_ADVERTISER,
                             "banner de loja", 1, title=alt or f"loja {sid.group(1) if sid else ''}", alt=alt, href=href,
                             img_src=img_src(img), evidence=["link do banner traz adsTrackingPayload (Shopee Ads)"],
                             extra={"shop_id": sid.group(1) if sid else ""}))
        elif alt.lower().startswith("lojas oficiais") and "/m/" in href:
            out.append(Piece("shopee", "paid", "official_store", find_brand(alt) or UNKNOWN_ADVERTISER,
                             "Lojas Oficiais", 1, title=alt, alt=alt, href=href, img_src=img_src(img),
                             evidence=["banner 'Lojas Oficiais' no carrossel principal (espaco vendido a lojas; selo Anuncio na peca)"]))
        elif "shopee.com.br/m/" in href and len(alt) > 25:
            out.append(Piece("shopee", "marketplace", "banner", "Shopee", "carrossel principal", 1, title=alt, alt=alt,
                             href=href, img_src=img_src(img), evidence=["banner de campanha /m/ sem marcador de anuncio"],
                             extra={"featured_brand": find_brand(alt) or ""}))
    return out


# ---------------------------------------------------------------------------
# Loja da propria marca
# ---------------------------------------------------------------------------
def _brand_store(key: str) -> Callable[[BeautifulSoup], List[Piece]]:
    brand = BRAND_STORES[key]

    def run(soup: BeautifulSoup) -> List[Piece]:
        out: List[Piece] = []
        for img in soup.find_all("img"):
            href = parent_href(img)
            alt = _clean(img.get("alt"), 200)
            if not href or "utmi_cp" not in href:
                continue
            q = parse_qs(urlparse(href).query)
            cp = (q.get("utmi_cp") or [""])[0]
            zone = (q.get("utmi_pc") or [""])[0].strip()
            out.append(Piece(key, "brand_store", "banner", brand, zone or "loja", None, title=alt or cp, alt=alt,
                             href=href, img_src=img_src(img),
                             evidence=[f"loja propria da marca (utmi_pc={zone}, utmi_cp={cp})"],
                             extra={"campaign": cp}))
        return out

    return run


# ---------------------------------------------------------------------------
# Generico: qualquer site
# ---------------------------------------------------------------------------
def _generic(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for lab in soup.find_all(string=SPONSOR_LABEL_RE):
        box = lab.parent
        for _ in range(6):
            if box.parent is None:
                break
            box = box.parent
            if box.find("img") or box.find("a"):
                break
        img = box.find("img")
        alt = _clean(img.get("alt") if img else "", 200)
        text = _clean(box.get_text(" "), 200)
        out.append(Piece("generic", "paid", "unknown", find_brand(alt, text) or UNKNOWN_ADVERTISER, "rotulado", None,
                         title=alt or text, alt=alt, href=parent_href(img) if img else "",
                         img_src=img_src(img) if img else "", evidence=[f"rotulo '{lab.strip()}' junto da peca"]))
    return out


RULES: Dict[str, Callable[[BeautifulSoup], List[Piece]]] = {
    "magalu": _magalu,
    "casasbahia": _casasbahia,
    "amazon": _amazon,
    "mercadolivre": _mercadolivre,
    "shopee": _shopee,
    "midea": _brand_store("midea"),
    "generic": _generic,
}


def detect(html: str, url: str = "", marketplace: Optional[str] = None) -> List[Piece]:
    """Le o HTML (renderizado ou salvo) e devolve as pecas classificadas."""
    key = marketplace or identify_marketplace(html, url)
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    rule = RULES.get(key, _generic)
    pieces = rule(soup)
    if key != "generic" and not any(p.is_paid for p in pieces):
        # site conhecido sem nenhum pago: tenta o rotulo generico antes de desistir
        pieces += [p for p in _generic(soup)]
        for p in pieces:
            p.marketplace = key
    return _dedupe(pieces)
