# Mapa de slots — como cada site marca o espaço pago

Levantado nas homes desktop de 11/11/2026 (`tests/fixtures/homes_2026-11-11`).
Implementado em `shelfproof/detect/rules.py`. Sites mudam o HTML: quando uma
regra parar de achar peças, salve a página (Ctrl+S), adicione como fixture e
ajuste a regra com teste.

## Magalu
- **Marcador:** alt `Abrir oferta patrocinada - slot <id>, posicao <n>`.
- **Anunciante:** destino `/selecao/<slug>` (`mideanov26`, `ssg_te_nov_26_ads_trio` = Samsung,
  `eluxdpznov26` = Electrolux, `iphone_17_nov_11.11` = Apple).
- **Slots vistos:** `desk_hypertop_Ads_small` (pos 1), `desk_home_Promo_large_carrossel_p1`,
  `desk_home_Ads_large_carrossel_p3..p5`, `desk_home_large_carrossel_p6_10` (mistura marca
  e campanha própria), `desk_home_Ads_medium` (pos 3), `desk_home_Ads_trio_superior_1..3`
  (pos 4), `desk_home_Ads_trio_meio_5` (pos 10), `desktop_magaluempresas` (pos 13).
- **Também:** banners laterais "Banner de ofertas do Magazine Luiza" com `/selecao/<marca>`;
  vitrine com título "Patrocinados" (cards de produto).
- **Armadilha:** slot com texto "patrocinada" e destino sem marca = campanha da Magalu (S3).

## Casas Bahia
- **Marcador:** `vtr_name=Ads_CB_<data>_<Marca>_<Desk|Mob>...` no link.
- **Campanha própria:** `vtr_name=<AAAAMMDD>gcb...` (ex.: `20261110gcbespec11.11gcbtelgcbbtv`).
- **Anunciante fora do dicionário:** o token antes de `Desk|Mob` é quem comprou
  (12/11/2026: `Ads_CB_v2_Belmicro_Desk` = Belmicro, distribuidora; a visão leu "HQ", marca
  dos produtos na peça). O nome do vtr_name vale mais que a leitura da imagem.
- **Sessão aquecida:** a vitrine "indicados com base nas suas visualizações" depende do
  histórico do perfil. Fica `marketplace`, mas não entra em comparação entre datas.
- Banners de oferta do varejista podem destacar uma marca (Philips, Midea) sem
  ser mídia vendida: ficam `marketplace` com `extra.featured_brand`.

## Amazon
- **Display:** `data-csa-c-slot-id="adplacements:Gateway:desktop-wp-1:..."` (anunciante não aparece no HTML).
- **Sponsored Products:** rótulo "Patrocinado" no card; marca pelo slug do link `/<Marca-...>/dp/<ASIN>`.
- **Sponsored Brands / display de produto:** rótulo "Patrocinado" + link `aax-*.amazon.com`;
  marca no título do bloco ("Ofertas Nivea") ou só na imagem (Neutrogena → leitura visual).
- **Gateway/hero:** imagens `_SF1282...`, `_SR428,684`, `DossierVisualNav` = campanha da Amazon.

- **Home anônima (12/11/2026, desktop, Chrome real):** nenhum rótulo "Patrocinado", nenhum
  `adplacements:*` e nenhum iframe de anúncio no DOM nem no print. A vitrine inteira era da
  própria Amazon ("Black dos Sonhos", Prime Video, Echo, Kindle). As peças pagas do 11.11 vieram
  da sessão **logada** (S1). Na home anônima, "0 pagas" é o dado, não falha do detector.

## Mercado Livre
- **Peças de display:** link `click1.mercadolivre.com.br/display/clicks/...`.
- **Pago:** código no alt com `_ADS_` (ex.: `MS_1111_ADS_BITLAR_MA` = Bitlar).
- **Campanha do ML:** demais peças de display (`MS_11a25_TECH_...`, "Cupom Relâmpago").

- **Home anônima (12/11/2026, desktop):** nenhuma peça com `_ADS_`. Os alts do hero agora são
  frases ("Black Friday. Só hoje!...") e não códigos `MS_...`. O componente `advertising-square`
  e o `action_id: "advertising"` do JSON da página aparecem **também** nas campanhas do próprio
  ML (Black Friday, Liquida Full, Especial Música): não são marcador de mídia vendida.
- **Cards de display da marca (pago):** card com `action_id: "advertising"` cuja marca aparece no
  destino (`/loja/apple`) ou no texto ("IPHONE 18 PRO") é espaço **vendido à marca** — confirmado
  por quem compra Mercado Ads em 12/11/2026. Sem marca, o mesmo componente é campanha do ML.
  São `<div>` com imagem de fundo CSS, sem `<img>`: `ELEMENTS_JS` também guarda essas peças.

## Shopee
- **Pago:** `adsTrackingPayload=` no link (banner de loja `/shop/<id>`).
- **Lojas Oficiais:** alt começa com "Lojas Oficiais" e a peça traz o selo "Anúncio".
- **Campanha da Shopee:** banners `/m/<campanha>` sem marcador.
- **Quem comprou o "Lojas Oficiais":** marca do dicionário no alt; senão o nome no alt
  ("Lojas Oficiais Bestway."); senão o destino `/m/<loja>-vN` (`dd-maquinas`, `bodyaction`),
  com `needs_review` para conferir a grafia.
- **Imagem:** o `<img src>` traz `<arquivo>` e o navegador baixa `<arquivo>@resize_w797_nl.webp`;
  o casamento ignora o sufixo de tamanho (`pipeline._src_key`).
- **Janela de idioma:** opções sem papel de botão; o robô clica "Português (BR)" só dentro da
  janela "Selecione seu idioma" (o cabeçalho tem o mesmo texto).

## Loja da marca (midea.com.br)
- Tudo é `brand_store`. A zona vem de `utmi_pc` (`banner_tv`, `banner_menu`,
  `vitrine_categorias`, `mosaico_*`, `oferta_relampago`) e a campanha de `utmi_cp`.

## Qualquer outro site (genérico)
- Rótulo visível "Patrocinado(s) / Publicidade / Anúncio / Sponsored" junto da peça.
- Sem rótulo = não é pago.
