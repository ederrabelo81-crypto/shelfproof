---
description: Cola uma URL e devolve o Showroom (captura desktop+mobile, classifica, monta e publica)
argument-hint: <url> [nome do evento]
---
Objetivo: gerar o Showroom de `$ARGUMENTS` no padrao de `reference/showroom_2026-11-11/index.html`.

1. Leia `CLAUDE.md` e `.claude/COMMON_MISTAKES.md` se ainda nao leu nesta sessao.
2. Rode `python -m shelfproof capture <url> --device both`. Se a captura vier com `blocked=true`
   ou poucas pecas, abra `full.jpg` e `manifest.json` antes de concluir qualquer coisa (R15/R22).
3. Mostre o resumo de `summary.json` (pagos por anunciante, share of pixels, pagos na 1a dobra).
4. Monte com `python -m shelfproof showroom <run_dir_desktop> --event "<evento>" --date <hoje> --out runs/showroom/<slug>`
   e gere a folha de contato (`contact-sheet`). Olhe a folha: pecas com celebridade ou pessoa
   real vao para `review.json` e o showroom e remontado com `--review`.
5. Anunciante `Nao identificado`: diga quantos e onde; nao chute.
6. Entregue o caminho do `index.html` e ofereca publicar como artifact (a pasta e autocontida).
