"""Detector de pecas e de propriedade do espaco (pago / marketplace / loja da marca).

Uma funcao por marketplace, porque cada um expoe o inventario de midia de um
jeito. Regras levantadas nas homes de 11/11/2026 (docs/MAPA_SLOTS.md):

* Magalu      alt "Abrir oferta patrocinada - slot <id>, posicao <n>" + link /selecao/<slug>
* Casas Bahia parametro vtr_name=Ads_CB_<data>_<Marca>_<device> no link do banner
* Amazon      rotulo "Patrocinado" no card + placements "adplacements:*" (data-csa-c-slot-id)
* Mercado Livre peca de display (click1.../display/clicks) com "_ADS_" no codigo do alt
* Shopee      adsTrackingPayload no link; banners de "Lojas Oficiais" no carrossel
* Loja da marca (dominio da propria marca) tudo e brand_store
* Especialistas de ar-condicionado (Frigelar, Dufrio, Leveros...: SPECIALISTS) -- banners da
  propria varejista; a marca em destaque vem do destino/alt/arquivo (extra.featured_brand).
  Pago so com rotulo visivel (generico), como em qualquer site.

REGRA DURA (herdada do RAC, COMMON_MISTAKES #15 e #20): evidencia antes de
string, e ausencia de dado e dado ausente. Toda peca "paid" carrega em
``evidence`` o marcador que a justificou; sem marcador, nao e paga. Anunciante
que o HTML nao revela fica ``Nao identificado`` -- nunca chutado.
"""
from __future__ import annotations

import re
from typing import Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from shelfproof.detect.brands import INGREDIENTS, find_brand, find_brand_first, find_brands, strip_ingredients
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

# Varejo especialista em ar-condicionado (Black Friday 2026). Nenhum deles marca espaco vendido a
# marca na home (24/11/2026: zero "Patrocinado", zero parametro de anuncio): banner de marca e
# banner da propria varejista com a marca em destaque, nao midia paga (regra dura 1).
# chave -> (host, nome, contexto extra de banner alem de _BANNER_CTX)
SPECIALISTS: Dict[str, "tuple[str, str, str]"] = {
    "friopecas": ("friopecas.com.br", "Friopeças", ""),
    "frigelar": ("frigelar.com.br", "Frigelar", ""),
    "webcontinental": ("webcontinental.com.br", "WebContinental", ""),
    "dufrio": ("dufrio.com.br", "Dufrio", ""),
    "poloar": ("poloar.com.br", "Poloar", ""),
    "climario": ("climario.com.br", "Clima Rio", ""),
    # home "v9" da CentralAr: hero (m01) e blocos de foto sem classe de banner
    "centralar": ("centralar.com.br", "CentralAr", r"ca-v9-m01|ca-v9-m09|ca-v9-m11"),
    "denteck": ("denteck.com.br", "Denteck", ""),
    "arcerto": ("arcerto.com", "ArCerto", ""),
    "leveros": ("leveros.com.br", "Leveros", ""),
    "refricril": ("refricril.com.br", "Refricril", ""),
}
MARKETPLACE_HOSTS.update({host: key for key, (host, _n, _c) in SPECIALISTS.items()})
MARKETPLACE_NAMES: Dict[str, str] = {
    "amazon": "Amazon",
    "mercadolivre": "Mercado Livre",
    "magalu": "Magalu",
    "casasbahia": "Casas Bahia",
    "shopee": "Shopee",
    "midea": "Loja Midea",
    "generic": "Site",
    **{key: name for key, (_h, name, _c) in SPECIALISTS.items()},
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
    for key, (h, _n, _c) in SPECIALISTS.items():  # antes de "midea": a home do especialista cita marcas
        if h in head:
            return key
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
_CB_DEVICE = re.compile(r"^(desk|desktop|mob|mobile|app)$", re.I)


def _cb_vtr_advertiser(parts: List[str]) -> str:
    """Nome do anunciante no padrao Ads_CB_<data|versao>_<Anunciante>_<Desk|Mob>_...: o token antes do dispositivo."""
    for i, tok in enumerate(parts):
        if _CB_DEVICE.match(tok) and i >= 3:
            cand = parts[i - 1]
            if re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9&+\-]{1,30}", cand) and not re.fullmatch(r"v\d+", cand, re.I):
                return cand
    return ""


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
            evidence = [f"vtr_name '{vtr}' (prefixo Ads_CB = midia vendida)"]
            brand = find_brand(" ".join(parts[2:]))
            named = _cb_vtr_advertiser(parts)
            if not brand and named:
                # o vtr_name nomeia quem comprou (12/11/2026: Ads_CB_v2_Belmicro_Desk), mesmo fora do dicionario
                brand = named
                evidence.append(f"anunciante nomeado no vtr_name: '{named}'")
            brand = brand or find_brand(alt) or UNKNOWN_ADVERTISER
            out.append(Piece("casasbahia", "paid", "banner", brand, vtr, 1, title=alt, alt=alt, href=href, img_src=src,
                             evidence=evidence))
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
            # link de login nunca e destino de anuncio (Amazon celular 17/11/2026: o card "Patrocinado"
            # pegava o /ap/signin do bloco ao lado e virava duas pecas iguais sem imagem)
            links = [x.get("href", "") for x in card.find_all("a")
                     if x.get("href") and "/ap/signin" not in x.get("href", "")]
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


_ML_CARD = re.compile(r'"action_id"\s*:\s*"advertising"\s*,\s*"link"\s*:\s*"([^"]+)"')


def _ml_brand_cards(html: str) -> List[Piece]:
    """Cards de display da home do ML (action_id "advertising") que levam uma MARCA.

    O mesmo componente carrega campanha do proprio ML (Black Friday, Liquida Full). Com marca
    no destino (/loja/apple) ou no texto (iPhone), o espaco e vendido a marca: confirmado por
    quem compra Mercado Ads em 12/11/2026. Sem marca, e campanha do ML (fica com o detector de display).
    """
    import html as _html

    text = _html.unescape(html).replace("\\u002F", "/").replace("\\/", "/")
    out: List[Piece] = []
    seen = set()
    for m in _ML_CARD.finditer(text):
        link = m.group(1)
        ctx = text[max(0, m.start() - 1500):m.start()]
        start = ctx.rfind('"content"')
        block = ctx[start:] if start >= 0 else ctx[-800:]
        titles = re.findall(r'"(?:volanta|primary_title|secondary_title|title)"\s*:\s*"([^"]{1,90})"', block)
        pic = (re.findall(r'"picture"\s*:\s*"(https://[^"]+)"', block) or [""])[-1]
        loja = re.search(r"/loja/([a-z0-9\-]+)", link)
        brand = find_brand(loja.group(1).replace("-", " ")) if loja else None
        where = f"destino /loja/{loja.group(1)}" if brand and loja else ""
        if not brand:
            brand = find_brand_first(re.sub(r"[-_/]", " ", urlparse(link).path))
            where = f"destino {urlparse(link).path[:60]}" if brand else ""
        if not brand:
            brand = find_brand_first(" ".join(titles))
            where = f"texto do card '{' '.join(titles)[:60]}'" if brand else ""
        ingredient_only = not brand and bool(INGREDIENTS.search(" ".join(titles)))
        key = urlparse(link).path or link
        if (not brand and not ingredient_only) or key in seen:
            continue
        if ingredient_only:
            # so marca de componente no texto (Sony LYTIA, Intel Core): e anuncio de marca, mas de QUEM
            # so a peca diz -> fica para a leitura visual
            brand, where = UNKNOWN_ADVERTISER, "texto do card (so marca de componente: precisa da leitura visual)"
        seen.add(key)
        out.append(Piece("mercadolivre", "paid", "display", brand, "card de display da home", None,
                         title=" ".join(titles)[:140], href=link, img_src=pic,
                         evidence=[f"card de display (action_id advertising) com a marca no {where}",
                                   "formato vendido a marca (confirmado com comprador de Mercado Ads, 12/11/2026)"]))
    return out


# ---------------------------------------------------------------------------
# Shopee
# ---------------------------------------------------------------------------
def _shopee_store_name(alt: str, href: str) -> "tuple[str, str]":
    """Loja que comprou o banner 'Lojas Oficiais' quando a marca nao esta no dicionario.

    12/11/2026: "Lojas Oficiais Bestway. Piscina..." (nome no alt) e /m/dd-maquinas-v10,
    /m/bodyaction-v5 (nome so no destino). O destino /m/<loja>-vN e a pagina da loja.
    """
    m = re.match(r"\s*lojas oficiais\s+([^.:,;]{2,40}?)\s*[.:,;]", alt, re.I)
    if m:
        return m.group(1).strip(), f"loja nomeada no texto do banner: '{m.group(1).strip()}'"
    s = re.search(r"/m/([a-z0-9\-]+?)(?:-v\d+)?/?(?:[?#]|$)", href)
    if s and not re.search(r"(campanha|ofertas|cupom|frete|11-11|black)", s.group(1)):
        name = " ".join(w.capitalize() for w in s.group(1).split("-"))
        return name, f"loja nomeada no destino /m/{s.group(1)}"
    return "", ""


_SHOPEE_BASE = "https://shopee.com.br"
_SHOPEE_AD_PREFIX = re.compile(r"^\s*an[uú]ncio\s*[.:\-]\s*", re.I)
# destino de loja/colecao vendida (17/11/2026 os links vem relativos: /shop/<id>, /collections/<id>, /m/<loja>)
_SHOPEE_STORE_DEST = re.compile(r"(?:^|shopee\.com\.br)/(shop|collections)/\d+|(?:^|shopee\.com\.br)/m/", re.I)


def _shopee(soup: BeautifulSoup) -> List[Piece]:
    out: List[Piece] = []
    for img in soup.find_all("img"):
        raw_href = parent_href(img)
        href = urljoin(_SHOPEE_BASE, raw_href) if raw_href else ""
        alt = _clean(img.get("alt"), 240)
        labeled = bool(_SHOPEE_AD_PREFIX.match(alt))      # "Anuncio. Lojas Oficiais Podium..." (17/11/2026)
        text = _SHOPEE_AD_PREFIX.sub("", alt) if labeled else alt
        dest = _SHOPEE_STORE_DEST.search(raw_href or "")
        if "adsTrackingPayload" in href:
            sid = re.search(r"/shop/(\d+)", href)
            out.append(Piece("shopee", "paid", "official_store", find_brand(alt) or UNKNOWN_ADVERTISER,
                             "banner de loja", 1, title=alt or f"loja {sid.group(1) if sid else ''}", alt=alt, href=href,
                             img_src=img_src(img), evidence=["link do banner traz adsTrackingPayload (Shopee Ads)"],
                             extra={"shop_id": sid.group(1) if sid else ""}))
        elif text.lower().startswith("lojas oficiais") and dest and (labeled or len(text) > 25):
            # "Lojas Oficiais. Cashback..." -> /oficial e a vitrine da propria Shopee: sem destino de loja, fica de fora
            evidence = ["texto da peca comeca com 'Anuncio.' (rotulo de midia paga)"] if labeled else []
            evidence.append("banner 'Lojas Oficiais' com destino de loja/colecao (espaco vendido a lojas)")
            extra: Dict[str, str] = {}
            sid = re.search(r"/(?:shop|collections)/(\d+)", raw_href or "")
            if sid:
                extra["shop_id"] = sid.group(1)
            brand = find_brand(text)
            if not brand:
                brand, how = _shopee_store_name(text, href)
                if brand:
                    evidence.append(how)
                    extra["needs_review"] = "nome da loja tirado do texto/destino: conferir grafia e incluir em brands.py"
            out.append(Piece("shopee", "paid", "official_store", brand or UNKNOWN_ADVERTISER,
                             "Lojas Oficiais", 1, title=alt, alt=alt, href=href, img_src=img_src(img),
                             evidence=evidence, extra=extra))
        elif labeled and dest:
            # rotulo "Anuncio." sem "Lojas Oficiais": pago, anunciante pela marca do texto ou pela visao
            out.append(Piece("shopee", "paid", "banner", find_brand(text) or UNKNOWN_ADVERTISER, "carrossel principal",
                             1, title=alt, alt=alt, href=href, img_src=img_src(img),
                             evidence=["texto da peca comeca com 'Anuncio.' (rotulo de midia paga)"]))
        elif re.match(r"^(?:https?://(?:www\.)?shopee\.com\.br)?/m/", raw_href or "") and len(alt) > 25:
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
# Varejo especialista em ar-condicionado
# ---------------------------------------------------------------------------
# Ancestral que diz "isto e banner/carrossel" (levantado nas 11 homes renderizadas em 24/11/2026)
_BANNER_CTX = re.compile(r"banner|slider|slide|carousel|swiper|hero|slick|keen|infocard|mosaic|brandmodule", re.I)
_LOGO_STRIP_CTX = re.compile(r"brands?[-_]?slid(?:e|er)|slider[-_]brands|brandmodule|^marcas$|ca-v9-m04", re.I)
_LOGO_STRIP_SRC = re.compile(r"slider-brands|brands-slider|home-brands|/logos?-?marcas?/", re.I)
# card de produto dentro de carrossel (Leveros: product-card; CentralAr: pdc_product-item; VTEX: product-summary)
_PRODUCT_CTX = re.compile(r"product|produto|shelf", re.I)
_PRODUCT_HREF = re.compile(r"/p/?(?:$|\?)|/p/[\w-]+|/produtos?/|/dp/|\.html(?:$|\?)", re.I)
_PRODUCT_SRC = re.compile(r"/arquivos/ids/|/produtos/foto/|/products/|/upload/produto/|/medias/[^/]*product", re.I)
_CHROME_HREF = re.compile(r"^(?:tel:|mailto:|javascript:)|whatsapp|wa\.me|instagram|facebook|youtube|tiktok|linkedin|"
                          r"reclameaqui|lojaconfiavel|play\.google|apps\.apple|vtex\.com|/login|/minha-conta|/blog/", re.I)
_SEP = re.compile(r"[-_/?=&.+%,;:]+")


def _ctx_tokens(img: Tag, depth: int = 10) -> List[str]:
    out: List[str] = []
    for i, anc in enumerate(img.parents):
        if i >= depth or anc.name in ("body", "html", "[document]"):
            break
        out += [c for c in (anc.get("class") or []) if isinstance(c, str)]
    return out


def _slot_name(tokens: List[str], pattern: "re.Pattern[str]") -> str:
    for t in tokens:
        if pattern.search(t):
            t = t.split("--")[-1] if "--" in t else t
            t = re.sub(r"^[\w-]*?-\d+-x-", "", t)  # VTEX IO: "vtex-slider-layout-0-x-imageElementLink"
            return re.sub(r"__[A-Za-z0-9-]{5}$", "", t)[:60]
    return ""


def _slug_text(u: str) -> str:
    """Destino ou nome de arquivo como texto: '/marcas/Springer-Midea/c/X' -> 'marcas Springer Midea c X'."""
    return _SEP.sub(" ", unquote(u or "")).strip()


def _specialist_brand(href: str, alt: str, src: str) -> "tuple[str, str, List[str]]":
    """Marca em destaque no banner, pela ordem de forca da evidencia: destino do clique, texto
    alternativo, nome do arquivo da peca. Mais de uma marca na mesma fonte = sem destaque unico."""
    p = urlparse(href or "")
    fname = urlparse(unquote(src or "")).path.rsplit("/", 1)[-1]
    if "/_next/image" in (src or ""):  # Next.js (Poloar): o arquivo real vem no parametro url
        inner = (parse_qs(urlparse(src).query).get("url") or [""])[0]
        fname = urlparse(inner).path.rsplit("/", 1)[-1] or fname
    fname = re.sub(r"___[0-9a-f]{32}", "", fname)  # VTEX file-manager: <uuid>___<hash>
    for source, text in (("destino", _slug_text(p.path + " " + p.query)), ("alt", alt), ("arquivo", _slug_text(fname))):
        found = find_brands([strip_ingredients(text)]) if text else []
        found = [b for b in found if not (b == "Midea" and "Springer Midea" in found)]
        if len(found) == 1:
            return found[0], source, found
        if len(found) > 1:
            return "", source, found
    return "", "", []


def _specialist(key: str) -> Callable[[BeautifulSoup], List[Piece]]:
    host, name, extra_ctx = SPECIALISTS[key]
    ctx_re = re.compile(_BANNER_CTX.pattern + (f"|{extra_ctx}" if extra_ctx else ""), re.I)

    def run(soup: BeautifulSoup) -> List[Piece]:
        out: List[Piece] = []
        for img in soup.find_all("img"):
            if img.find_parent("footer"):
                continue
            src = img_src(img)
            if not src or src.startswith("data:") or re.search(r"\.svg(?:$|\?)", src, re.I):
                continue
            if re.search(r"no-image|placeholder|blank\.(?:gif|png)|loading\.gif", src, re.I):
                continue  # lazy-load ainda sem a peca (Frigelar: /img/no-image.jpg)
            href = parent_href(img).strip()
            alt = _clean(img.get("alt"), 200)
            if _PRODUCT_HREF.search(href) or _PRODUCT_SRC.search(unquote(src)) or _CHROME_HREF.search(href):
                continue
            dest = urlparse(href)
            if href == "/" or (dest.path in ("", "/") and dest.netloc.endswith(host)):
                continue  # logo da loja
            w = re.search(r"[?&](?:width|w)=(\d+)", src)
            attr_w = str(img.get("width") or "")
            if (w and int(w.group(1)) < 120) or (attr_w.isdigit() and int(attr_w) < 120):
                continue  # icone
            tokens = _ctx_tokens(img)
            if any(_PRODUCT_CTX.search(t) for t in tokens):
                continue
            slot = _slot_name(tokens, ctx_re)
            if not slot and not re.search(r"/banners?/", src, re.I) and not re.match(r"banner\b", alt, re.I):
                continue  # nao esta em banner/carrossel: vitrine de produto, icone, cabecalho
            # faixa de logos (navegacao por marca), pela classe ou pela pasta do arquivo (Leveros:
            # /upload/menu/b2c-home-slider-brands/): logo pequeno nao e banner de destaque
            logo_strip = bool(_slot_name(tokens, _LOGO_STRIP_CTX)) or bool(_LOGO_STRIP_SRC.search(src))
            brand, source, seen = _specialist_brand(href, alt, src)
            evidence = ["banner da propria varejista: nenhum rotulo de patrocinio nem parametro de anuncio"]
            extra: Dict[str, str] = {"featured_brand": brand, "needs_box": "1"}
            if brand:
                where = {"destino": f"destino do clique '{href}'", "alt": f"texto alternativo '{alt}'",
                         "arquivo": "nome do arquivo da peca"}[source]
                evidence.append(f"marca em destaque: {brand} ({where})")
                extra["featured_brand_source"] = source
            elif len(seen) > 1:
                extra["brands_seen"] = ", ".join(seen)
            if logo_strip:
                extra["logo_strip"] = "1"
            pic = img.find_parent("picture")  # o lxml aninha <img> dentro de <source>: o ancestral resolve
            if pic is not None:
                # <picture> (Leveros 24/11/2026): o <img src> e a versao de celular e o navegador mostra a do
                # <source> de desktop. O pipeline casa a peca com qualquer uma das fontes.
                cands = [(so.get("srcset") or so.get("data-srcset") or "").split(",")[0].strip().split(" ")[0]
                         for so in pic.find_all("source")]
                cands = [c for c in cands if c and not c.startswith("data:")]
                if cands:
                    extra["src_candidates"] = " ".join(cands)
            if re.search(r"\btrade\b", alt, re.I):
                # Dufrio 24/11/2026: alt "Banner TCL Trade". Indicio de verba de trade, nao marcador
                # de midia vendida: fica marketplace, para o analista conferir com a marca.
                extra["trade_hint"] = f"alt cita 'Trade': '{alt}'"
            out.append(Piece(key, "marketplace", "banner", name, "faixa de marcas" if logo_strip else (slot or "banner"),
                             None, title=alt or (f"banner {brand}" if brand else "banner sem texto"), alt=alt, href=href, img_src=src,
                             evidence=evidence, extra=extra))
        return out

    return run


def _dedupe_specialist(pieces: List[Piece]) -> List[Piece]:
    """Varias pecas levam ao MESMO destino (Poloar: 6 banners para /ar-condicionado?...): aqui o
    clone do carrossel e a mesma imagem no mesmo slot, nao o mesmo link."""
    seen, out = set(), []
    for p in pieces:
        if not p.is_paid:
            # mesma imagem em outro tamanho = clone; /_next/image?url=<arquivo> (Poloar) e outra peca por url
            key = (p.slot, re.sub(r"[?&](?:w|width|h|height|q|quality|format|aspect|v)=[^&]*", "", p.img_src))
            if key in seen:
                continue
            seen.add(key)
        out.append(p)
    return out


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
    **{key: _specialist(key) for key in SPECIALISTS},
}


def detect(html: str, url: str = "", marketplace: Optional[str] = None) -> List[Piece]:
    """Le o HTML (renderizado ou salvo) e devolve as pecas classificadas."""
    key = marketplace or identify_marketplace(html, url)
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    rule = RULES.get(key, _generic)
    pieces = rule(soup)
    if key == "mercadolivre":
        pieces += _ml_brand_cards(html)
    if key != "generic" and not any(p.is_paid for p in pieces):
        # site conhecido sem nenhum pago: tenta o rotulo generico antes de desistir
        pieces += [p for p in _generic(soup)]
        for p in pieces:
            p.marketplace = key
    if key in SPECIALISTS:
        base = url or f"https://www.{SPECIALISTS[key][0]}/"
        for p in pieces:  # link/imagem relativos: absolutos, como o navegador grava em elements.json
            p.href = urljoin(base, p.href) if p.href else ""
            p.img_src = urljoin(base, p.img_src) if p.img_src else ""
            if p.extra.get("src_candidates"):
                p.extra["src_candidates"] = " ".join(urljoin(base, c) for c in p.extra["src_candidates"].split())
        return _dedupe_specialist(pieces)
    return _dedupe(pieces)
