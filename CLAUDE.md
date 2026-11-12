# Shelf Proof (Showroom) — Regras do projeto

> **O que é:** robô que abre home pages de marketplaces e sites como um cliente,
> fotografa tudo, separa **mídia paga x campanha do marketplace x loja da marca**
> e entrega um **Showroom**: infográfico visual com as peças reais em loop, ranking
> de quem comprou espaço e a **prova de veiculação** de cada anúncio.
> **Para quem:** indústrias/marcas e agências que compram retail media e precisam
> provar que o anúncio foi ao ar, e comparar exposição em datas quentes
> (11.11, Black Friday, Dia do Consumidor).
> **Stack:** Python 3.10+, Playwright/rebrowser-playwright via CDP, BeautifulSoup,
> Pillow, Jinja2. Mesmo PC coletor (Windows, IP residencial) do RAC Position Tracker.
> **Irmão mais velho:** `rac-position-tracker` (mesma pasta Downloads). Este
> projeto herdou dele o navegador, as regras duras e os erros já pagos.

---

## Objetivo final (a régua de "pronto")

`reference/showroom_2026-11-11/index.html` é o **alvo visual aprovado** (12/11/2026).
Abra no navegador antes de mexer em qualquer coisa de saída. Tudo o que o robô
coleta existe para produzir esta página, automaticamente, a partir de uma lista
de URLs:

1. **Video wall** — uma tela por site, as peças reais girando em loop, etiqueta
   PAGO / MARKETPLACE / LOJA DA MARCA + anunciante + código do slot.
2. **Faixa de logos** dos anunciantes (recortados das próprias peças).
3. **Quem pagou para aparecer** — ranking com logo, barra e onde comprou.
4. **De quem é cada home** — pago x marketplace x marca por site.
5. **Proof of Placement** — por anunciante: peça, página, slot, posição, data/hora,
   selo "Veiculado ✓".

Especificação completa: `docs/OBJETIVO_SHOWROOM.md`. Plano: `docs/ROADMAP.md`.

## Session Start Protocol

Carregue nesta ordem:
1. `CLAUDE.md` (este arquivo)
2. `.claude/COMMON_MISTAKES.md` ⚠️ — erros que já custaram coleta (herdados do RAC + novos)
3. `.claude/ARCHITECTURE_MAP.md` — onde está cada coisa e o fluxo de dados
4. `docs/MAPA_SLOTS.md` — como cada marketplace marca o espaço pago

Se for mexer no navegador/CDP, leia também os guias do RAC (não copiados aqui):
`../rac-position-tracker/docs/COLETA_LOCAL_AUTENTICADA.md` e
`../rac-position-tracker/docs/cdp_magalu_collection.md`.

## Regras duras

1. **Evidência antes de string.** Peça só é `paid` com um marcador concreto
   (rótulo, código de slot, parâmetro de link) gravado em `Piece.evidence`.
   O teste `test_toda_peca_paga_tem_evidencia` reprova o contrário.
2. **Anunciante desconhecido fica `Nao identificado`.** Nunca chutar marca pela
   categoria ou pela cor do banner. Quem resolve é a leitura visual (fase 3,
   `shelfproof/vision/`), e só com marca escrita/logo visível e confiança alta ou
   média, gravada em `evidence` como "lido na imagem". A visão nunca cria peça paga.
3. **Sessão anônima limpa por padrão.** Home logada é personalizada (no 11.11, o
   histórico do usuário fez ar-condicionado dominar Amazon e ML). Persona logada
   (`--session profile`) é uma coleta **separada** e sempre rotulada.
   Exceção autorizada em 12/11/2026: **`anon_warm`** para sites com Akamai (Magalu,
   Casas Bahia), que negam contexto novo e vazio (403). Usa a sessão do perfil
   dedicado `chrome_profile_shelfproof`, que **nunca** faz login e só visita homes,
   aquecida na home (espera o `_abck` validar). Só desktop. Rotulada no manifest
   (`session`, `warmup`). Nunca logar nesse perfil nem navegar produtos nele.
4. **Chrome COMUM + CDP**, porta **9223** e perfil `data/chrome_profile_shelfproof`
   (o RAC usa 9222 e `data/chrome_profile`; os dois rodam no mesmo PC). Nunca
   `launch_persistent_context` em site com antibot. `--engine launch` é só para
   site sem antibot e para testes.
5. **Um `sync_playwright()` por thread** — sempre via `shelfproof.browser.playwright_runtime`.
6. **Chrome morto ≠ bloqueio.** Bloqueio = pouca imagem **e** frase de captcha.
   Gravar a evidência (print + HTML) em todo bloqueio.
7. **Cada artefato no seu próprio try/except** (print, HTML, elements, imagens).
   Um que falha não leva os outros. A pasta da captura sempre tem `manifest.json`
   com os erros.
8. **Celebridade/pessoa real não vai para o Showroom publicado.** Revisão humana
   pela folha de contato (`python -m shelfproof contact-sheet`) e `review.json`
   (`{"exclude": ["ml_04", ...]}`). O espaço pago excluído continua contando no
   ranking, sem imagem.
9. **Logos de marca** vêm de `assets/logos/<slug>.png`, recortados das peças
   capturadas (são parte da evidência). Não desenhar nem baixar logo de banco de imagens.
10. **O Showroom é autocontido**: HTML + `img/` + `logo/`, sem chamada externa
    (a política de conteúdo do artifact bloqueia imagem remota).
11. **Scripts Windows (.bat/.ps1) 100% ASCII** (COMMON_MISTAKES #13 do RAC).
12. **Mudou uma regra do detector?** Rode `pytest`. Os números de
    `tests/test_rules_11_11.py` foram conferidos peça a peça; se quebrar,
    confira a peça antes de mexer no teste.
13. **Coleta não ultrapassa o comportamento de um cliente**: páginas públicas,
    ritmo humano, sem login de terceiros, sem burlar captcha. Termos de uso
    dos marketplaces: avaliar com jurídico antes de vender.

## Comandos

```bash
pip install -r requirements.txt && playwright install chromium
pytest -q                                   # 44 testes; o e2e pula sem Chrome

# Uma URL (desktop + mobile), anônimo, via Chrome comum (RAC_LOCAL_CHROME=1)
python -m shelfproof capture https://www.magazineluiza.com.br/ --device both

# Magalu/Casas Bahia (Akamai): sessao anonima aquecida, so desktop
python -m shelfproof capture https://www.magazineluiza.com.br/ --session anon_warm --vision

# Página salva com Ctrl+S (como as do 11.11)
python -m shelfproof detect-file pagina.html --paid-only

# Fase 3: anunciante lido na imagem (precisa de ANTHROPIC_API_KEY no .env)
python -m shelfproof analyze --vision runs/<data>/<captura>
python -m shelfproof vision-eval            # acerto no 11.11: >= 80% e 0 erradas

# Evento inteiro: todas as homes de config/targets.json -> Showroom
python -m shelfproof event --event "Black Friday" --date 27/11/2026
python -m shelfproof contact-sheet runs/showroom/black-friday   # revisar, depois:
python -m shelfproof showroom <run_dirs...> --event "Black Friday" --date 27/11/2026 \
       --out runs/showroom/black-friday --review review.json
```

Windows (PC coletor): `scripts\coleta_evento.bat "Black Friday" 27/11/2026`.

## Convenções

- Português no domínio e nos docs; código e identificadores em inglês, como no RAC.
- Tipos explícitos, dataclasses, `loguru` para log, sem `except:` nu.
- Horário sempre BRT (`collect.capture.now_brt`).
- Commits: `tipo(escopo): descrição` (feat, fix, docs, test, refactor).
- Segredo nunca no repositório (`.env` é gitignored; `data/` e `runs/` também).
