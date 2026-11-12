---
description: Ensina o detector a ler um site novo (ou um site que mudou) a partir de uma pagina salva
argument-hint: <arquivo.html salvo com Ctrl+S> [url]
---
1. `python -m shelfproof detect-file $ARGUMENTS` e veja o que ja sai.
2. Procure no HTML os marcadores de midia paga (rotulo visivel, codigo de slot, parametro de
   rastreio no link). Registre em `docs/MAPA_SLOTS.md` com exemplo real.
3. Implemente a regra em `shelfproof/detect/rules.py` (uma funcao por site, evidencia em toda peca paga).
4. Salve a pagina em `tests/fixtures/homes_<data>/<site>.html.gz` e escreva o teste com os
   numeros conferidos peca a peca. `pytest -q` verde antes de terminar.
