# Architecture Map — Shelf Proof

```
shelf-proof/
├── CLAUDE.md                     # regras duras + objetivo
├── config/targets.json           # homes monitoradas (URL x dispositivos)
├── shelfproof/
│   ├── models.py                 # Piece, BBox (hierarquia Captura > Zona > Slot > Peça > Item)
│   ├── cli.py / __main__.py      # capture | analyze | detect-file | showroom | contact-sheet | event
│   ├── pipeline.py               # captura -> pieces.json + summary.json (caixa, dobra, imagem, tempo no ar)
│   ├── browser/                  # VENDORIZADO do RAC: playwright_runtime + local_browser (+ new_isolated_context)
│   ├── collect/capture.py        # robô: abre, observa carrossel, rola, salva print/HTML/imagens/elements
│   ├── detect/
│   │   ├── rules.py              # uma função por marketplace + genérico (rótulo Patrocinado/Anúncio)
│   │   └── brands.py             # dicionário de marcas e aliases de slug (ssg_ = Samsung, elux = Electrolux)
│   ├── vision/
│   │   ├── advertiser.py         # fase 3: anunciante lido na imagem (Claude API), cache vision.json
│   │   └── evaluate.py           # vision-eval: acerto contra as peças pagas do 11.11
│   └── render/
│       ├── showroom.py           # dados -> index.html + img/ + logo/
│       ├── contact_sheet.py      # folha de contato para revisão humana
│       └── templates/showroom.html.j2   # o Showroom aprovado, com DATA em JSON
├── assets/logos/                 # logos recortados das peças (slug.png)
├── reference/showroom_2026-11-11/      # ALVO VISUAL aprovado + data.json + placements_v1.csv
├── tests/
│   ├── fixtures/homes_2026-11-11/      # 6 homes salvas em 11/11 (gzip) — regressão do detector
│   ├── fixtures/mock_magalu/           # home falsa para o e2e do robô
│   ├── test_rules_11_11.py
│   ├── test_capture_e2e.py
│   └── test_render.py
├── scripts/                      # .bat ASCII para o PC coletor
├── docs/                         # objetivo, mapa de slots, roadmap
└── runs/                         # saída (gitignored)
```

## Fluxo

```
config/targets.json ─► capture()  (Chrome comum via CDP, contexto anônimo, desktop|mobile)
                         │  frames/ (1ª tela a cada 3 s)  page.html  elements.json  full.jpg  images/
                         ▼
                      analyze()   detect(page.html)  ─► quem é pago, de quem, slot, posição, evidência
                                  + elements.json   ─► caixa, área, dobra
                                  + images.json     ─► arquivo do criativo
                                  + frames          ─► tempo no ar na 1ª tela
                         ▼
                      [--vision]  pagas "Nao identificado" ─► leitura da imagem ─► vision.json
                         ▼
                      pieces.json + summary.json (share of pixels, pagos por anunciante)
                         ▼
                      contact-sheet ─► revisão humana ─► review.json
                         ▼
                      showroom     ─► index.html + img/ + logo/ (publicar como artifact)
```

## Onde mexer

| Preciso... | Arquivo |
|---|---|
| Novo site / nova regra de anúncio | `detect/rules.py` (+ teste com HTML salvo em `tests/fixtures`) |
| Nova marca ou alias de slug | `detect/brands.py` |
| Tempo de observação do carrossel, viewport, UA | `collect/capture.py` (`CaptureConfig`, `DEVICES`) |
| Prompt/aceite da leitura visual | `vision/advertiser.py` (`SYSTEM`, `accept`) + `pytest tests/test_vision.py` + `vision-eval` |
| Visual do Showroom | `render/templates/showroom.html.j2` |
| Lista de homes de um evento | `config/targets.json` |
| Porta/perfil do Chrome | `.env` (`RAC_CDP_PORT`, `RAC_CHROME_PROFILE_DIR`) |
