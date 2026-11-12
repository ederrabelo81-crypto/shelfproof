# Roadmap — Shelf Proof

Data-alvo: **Black Friday, 27/11/2026**. Primeira validação de campo no PC coletor.

| Fase | Entrega | Critério de aceite | Status |
|---|---|---|---|
| 0 · Protótipo | Leitura de HTML salvo + Showroom manual do 11.11 | Showroom aprovado | ✅ 12/11 |
| 1 · Esqueleto | Projeto, detector com regressão nas 6 homes, robô, pipeline, template | `pytest` verde (19), e2e local | ✅ 12/11 |
| 2 · Campo | Rodar `capture` nas 6 homes reais, desktop + mobile, sem login | 6×2 capturas com `ok=true`; regras ajustadas para o HTML **renderizado** e para o **mobile** | ⬜ até 18/11 |
| 3 · Visão | Anunciante pela imagem quando o HTML não diz (displays Amazon/ML, Sponsored Brands) | ≥ 80% dos `Nao identificado` resolvidos, com a evidência "lido na imagem" | ⬜ até 22/11 |
| 4 · Evento | `event` agendado a cada 2 h no dia; rotação e tempo no ar ao longo do dia | Showroom da BF com desktop × mobile e tempo no ar | ⬜ 27/11 |
| 5 · Prova | Recorte do slot no print + PDF de evidência por anunciante | PDF de uma marca pronto para enviar | ⬜ dez/26 |
| 6 · Jornada | Home → categoria → busca → produto; funil de exposição | 1 jornada roteirizada por site | ⬜ dez/26 |
| 7 · Produto | Histórico por evento, comparação entre datas, multi-cliente | Portal ou relatório recorrente | ⬜ 2027 |

## Fase 2 — tarefas iniciais (para a primeira sessão no Claude Code)

1. `pip install -r requirements.txt`, `playwright install chromium`, copiar `.env.example` para `.env`.
2. `pytest -q` (deve dar 19 passados no PC, inclusive o e2e).
3. `scripts\coleta_evento.bat` **não** ainda: começar por uma URL:
   `python -m shelfproof capture https://www.magazineluiza.com.br/ --device both`.
4. Conferir `runs/<data>/<captura>/full.jpg` e `pieces.json`. Se o número de pagos
   vier muito abaixo do 11.11, comparar `page.html` renderizado com a fixture salva
   e ajustar a regra (o HTML salvo com Ctrl+S e o DOM renderizado podem diferir).
5. Repetir para Amazon, ML, Casas Bahia, Shopee e Midea. Mobile tende a ter
   slots com outro nome (`mob_...`): mapear em `docs/MAPA_SLOTS.md`.
6. Guardar 1 `page.html` de cada (desktop e mobile) em `tests/fixtures/homes_<data>/`
   e escrever os testes do mobile.

## Riscos

- Antibot (Akamai na Magalu/Casas Bahia, gate no ML): mesma mitigação do RAC
  (Chrome comum, IP residencial, ritmo humano). Bloqueio vira evidência, não zero silencioso.
- Personalização por CEP/horário: declarar sempre as condições da coleta.
- Prova é amostragem, não contagem de impressões: vender assim.
- Termos de uso: só páginas públicas, sem login de terceiros; validar com jurídico antes de vender.
