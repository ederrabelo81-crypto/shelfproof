# Objetivo: o Showroom

Referência aprovada: `reference/showroom_2026-11-11/index.html` (abrir no navegador).
Publicada em claude.ai como "ShelfProof 11.11 Showroom".

## Para que serve

Duas promessas comerciais, um mesmo motor:

- **Proof of Placement** — "paguei o banner, ele apareceu?" Resposta com a peça,
  a página, o slot, a posição, a hora e o tempo no ar.
- **Share of Shelf em datas quentes** — "quem dominou a vitrine no 11.11 / na
  Black Friday, com que ofertas, em que sites, desktop x mobile?"

## Seções e de onde vem cada dado

| Seção | Mostra | Fonte no pipeline |
|---|---|---|
| Barra superior | data, dispositivos, nº de páginas | `manifest.json` das capturas |
| Hero + KPIs | peças capturadas, espaços pagos, anunciantes com nome, maior comprador | `pieces.json` (todas as runs) |
| Faixa de logos | anunciantes com logo | `assets/logos/` ∩ anunciantes pagos |
| Video wall | uma tela por site, peças em loop, etiqueta PAGO/MARKETPLACE/LOJA DA MARCA + anunciante + slot | `pieces.json` + `images/` |
| Quem pagou | ranking por nº de posições pagas, onde comprou | `Piece.is_paid`, `advertiser`, `marketplace` |
| De quem é cada home | barra pago x marketplace x marca por site | `Piece.ownership` |
| Proof of Placement | cartões por anunciante: peça, página, slot, posição, coleta, selo | `Piece` + `manifest.collected_at` |
| Metodologia | como foi lido, o que ficou de fora | contexto do evento |

## Próximas camadas (ainda não estão na referência)

1. **Desktop x mobile lado a lado** por site (o robô já captura os dois).
2. **Tempo no ar** do slide do carrossel (`airtime_first_screen`) e rotação ao
   longo do dia (capturas a cada 1–2 h no evento).
3. **Share of pixels** (área × dobra) no lugar da contagem pura (`summary.json`).
4. **Print com o slot destacado** no cartão de prova (recorte de `full.jpg` pela `bbox`).
5. **PDF de evidência** por anunciante (o que se entrega ao cliente pagante).
6. **Jornada**: home → categoria → busca → produto, com o funil de exposição.

## Critério de pronto do MVP (Black Friday 27/11/2026)

- `python -m shelfproof event ...` captura as 6 homes de `config/targets.json`
  em desktop e mobile, sem login, no PC coletor.
- Cada captura tem `page.html`, `full.jpg`, `frames/`, `images/`, `pieces.json`.
- O Showroom sai do comando com peças reais, ranking e prova, no mesmo visual
  da referência, depois da revisão da folha de contato.
- Nenhuma peça paga sem evidência; nenhum anunciante chutado.
