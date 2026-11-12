# Roadmap — Shelf Proof

Data-alvo: **Black Friday, 27/11/2026**. Primeira validação de campo no PC coletor.

| Fase | Entrega | Critério de aceite | Status |
|---|---|---|---|
| 0 · Protótipo | Leitura de HTML salvo + Showroom manual do 11.11 | Showroom aprovado | ✅ 12/11 |
| 1 · Esqueleto | Projeto, detector com regressão nas 6 homes, robô, pipeline, template | `pytest` verde (19), e2e local | ✅ 12/11 |
| 2 · Campo | Rodar `capture` nas 6 homes reais, desktop + mobile, sem login | 6×2 capturas com `ok=true`; regras ajustadas para o HTML **renderizado** e para o **mobile** | ⬜ até 18/11 |
| 3 · Visão | Anunciante pela imagem quando o HTML não diz (displays Amazon/ML, Sponsored Brands) | ≥ 80% dos `Nao identificado` resolvidos, com a evidência "lido na imagem", e **nenhuma marca errada** (`vision-eval`) | ✅ 12/11: 17/19 certas, 0 erradas (89,5%) |
| 4 · Evento | `event` agendado a cada 2 h no dia; rotação e tempo no ar ao longo do dia | Showroom da BF com desktop × mobile e tempo no ar | ⬜ 27/11 |
| 5 · Prova | Recorte do slot no print + PDF de evidência por anunciante | PDF de uma marca pronto para enviar | ⬜ dez/26 |
| 6 · Jornada | Home → categoria → busca → produto; funil de exposição | 1 jornada roteirizada por site | ⬜ dez/26 |
| 7 · Produto | Histórico por evento, comparação entre datas, multi-cliente | Portal ou relatório recorrente | ⬜ 2027 |

## Fase 2 — tarefas iniciais (para a primeira sessão no Claude Code)

1. `pip install -r requirements.txt`, `playwright install chromium`, copiar `.env.example` para `.env`.
2. `pytest -q` (deve dar 42 passados no PC, inclusive o e2e).
3. `scripts\coleta_evento.bat` **não** ainda: começar por uma URL:
   `python -m shelfproof capture https://www.magazineluiza.com.br/ --session anon_warm` (Magalu e Casas Bahia
   precisam da sessão aquecida; ver COMMON_MISTAKES S11).
4. Conferir `runs/<data>/<captura>/full.jpg` e `pieces.json`. Se o número de pagos
   vier muito abaixo do 11.11, comparar `page.html` renderizado com a fixture salva
   e ajustar a regra (o HTML salvo com Ctrl+S e o DOM renderizado podem diferir).
5. Repetir para Amazon, ML, Casas Bahia, Shopee e Midea. Mobile tende a ter
   slots com outro nome (`mob_...`): mapear em `docs/MAPA_SLOTS.md`.
6. Guardar 1 `page.html` de cada (desktop e mobile) em `tests/fixtures/homes_<data>/`
   e escrever os testes do mobile.

## Fase 3 — como está

- `shelfproof/vision/advertiser.py`: Claude (visão + saída estruturada) lê a peça paga
  `Nao identificado` e devolve marca, texto/logo visto, confiança e se há pessoa real.
- Aceita só confiança alta/média com marca escrita ou logo visível; o nome do próprio
  marketplace não vale como anunciante. Nunca muda `ownership` nem um anunciante que o HTML deu.
- Toda leitura fica em `<captura>/vision.json` (sha256 da imagem): reanalisar não paga de novo.
- Ligar: `python -m shelfproof analyze --vision <captura>` (também em `capture` e `event`).
- Medir: `python -m shelfproof vision-eval` esconde o anunciante das peças pagas do 11.11
  conferidas à mão e compara. Critério: ≥ 80% certas e 0 erradas.
- Resultado do `vision-eval` em 12/11 (Opus 5.5): 17 certas, 0 erradas, 2 abstenções corretas
  (`amazon_05` é uma imagem em branco na referência; `magalu_17` só mostra "cartão Magalu" —
  na coleta real o HTML já dá Samsung e ela nem vai para a visão).
- `ml_06` (pré-venda GTA VI, `MS_11a25_TECH_PREVENDAGTA_SEG`) estava marcada como paga na
  referência, mas o código não tem `_ADS_`: corrigida para campanha do Mercado Livre em 12/11,
  coerente com o detector. O eval passa a ter 19 peças pagas, todas com gabarito.
- Marca lida fora do dicionário de `brands.py` (ex.: a `ml_06` voltou "Grand Theft Auto
  (Rockstar Games)", nome de franquia) entra com `needs_review` e aparece em `summary.json` → `paid_needs_review`:
  conferir e, se for o caso, incluir a marca no dicionário.
- `people_present=sim` em `Piece.extra` ajuda a folha de contato; a decisão continua humana (regra 8).

## Riscos

- Antibot (Akamai na Magalu/Casas Bahia, gate no ML): mesma mitigação do RAC
  (Chrome comum, IP residencial, ritmo humano). Bloqueio vira evidência, não zero silencioso.
- Personalização por CEP/horário: declarar sempre as condições da coleta.
- Prova é amostragem, não contagem de impressões: vender assim.
- Termos de uso: só páginas públicas, sem login de terceiros; validar com jurídico antes de vender.
