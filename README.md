# Shelf Proof · Showroom

Prova de vitrine para marketplaces: **quem comprou cada espaço, onde, quando e por quanto tempo ficou no ar**.

Cole uma URL (ou rode o evento inteiro), e o robô abre a página como um cliente
anônimo em desktop e celular, observa o carrossel girando, rola até o fim,
guarda print, HTML e as imagens reais, classifica cada peça entre **mídia paga**,
**campanha do marketplace** e **loja da marca**, e monta o **Showroom**: video wall
com as peças em loop, ranking de anunciantes com logo, propriedade de cada home
e prova de veiculação por anunciante.

Alvo visual: `reference/showroom_2026-11-11/index.html` (11.11 de 2026).

## Instalação (PC coletor, Windows)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
pytest -q
```

## Uso

```bash
# uma URL, desktop + mobile, sessão anônima
python -m shelfproof capture https://www.magazineluiza.com.br/ --device both

# Magalu/Casas Bahia (Akamai): sessao anonima aquecida, so desktop
python -m shelfproof capture https://www.magazineluiza.com.br/ --session anon_warm --vision

# uma página salva com Ctrl+S
python -m shelfproof detect-file "Black Friday Magalu.html" --paid-only

# evento: todas as homes de config/targets.json -> Showroom
python -m shelfproof event --event "Black Friday" --date 27/11/2026

# anunciante lido na imagem quando o HTML não diz (Claude API, ANTHROPIC_API_KEY no .env)
python -m shelfproof analyze --vision runs/<data>/<captura>
python -m shelfproof vision-eval

# revisão e montagem final
python -m shelfproof contact-sheet runs/showroom/black-friday
python -m shelfproof showroom <runs desktop...> --event "Black Friday" --date 27/11/2026 --out runs/showroom/black-friday --review review.json
```

## Saída de uma captura

```
runs/2026-11-27/magazineluiza-com-br_desktop_anon_080102/
  manifest.json   URL, horário BRT, dispositivo, sessão, erros, bloqueio
  page.html       DOM renderizado
  elements.json   cada imagem com caixa na página, link e rótulo próximo
  full.jpg        print da página inteira
  frames/         1ª tela a cada 3 s (rotação do carrossel)
  images/         criativos exatamente como foram servidos
  pieces.json     peças classificadas (pago/marketplace/marca, anunciante, slot, evidência, dobra, tempo no ar)
  summary.json    pagos por anunciante, share of pixels, pagos na 1ª dobra
```

## Documentação

- `CLAUDE.md` — regras duras e objetivo (comece por aqui)
- `docs/OBJETIVO_SHOWROOM.md` — o que o Showroom mostra e de onde vem cada dado
- `docs/MAPA_SLOTS.md` — como cada marketplace marca o espaço pago
- `docs/ROADMAP.md` — fases até a Black Friday e depois
- `.claude/COMMON_MISTAKES.md` — erros herdados do RAC Position Tracker e novos

O navegador (`shelfproof/browser/`) é vendorizado do RAC Position Tracker.
