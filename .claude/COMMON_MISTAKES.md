# Common Mistakes — Shelf Proof

Parte 1 = herdados do RAC Position Tracker (resumo; o texto completo e a história
de cada um estão em `../rac-position-tracker/.claude/COMMON_MISTAKES.md`).
Parte 2 = aprendidos neste projeto.

## Parte 1 — herdados do RAC

### R10. Coleta local: Chrome COMUM + CDP (não perfil copiado, não Playwright launch)
Chrome 136+ ignora `--remote-debugging-port` no perfil padrão; copiar perfil
desloga; `launch_persistent_context` sobe com marcas de automação → Akamai 403.
**Certo:** Chrome comum, perfil dedicado estável, `connect_over_cdp` com
rebrowser-playwright (oculta `Runtime.enable`). Aqui: `shelfproof/browser/local_browser.py`.

### R13. Caractere não-ASCII em .ps1/.bat quebra o parse no Windows PowerShell 5.1
Travessão/acento em string de `.ps1` vira aspa tipográfica e fecha a string.
**Certo:** scripts Windows 100% ASCII. Validar: `grep -nP '[^\x00-\x7F]' scripts/*`.

### R14. User-Agent de outra família no Chromium
UA Firefox num Chromium = mismatch clássico de bot. **Certo:** só UA Chrome/Edge
(`collect/capture.py` DEVICES).

### R15. Detectar bloqueio por STRING sem olhar se a página tem conteúdo
O DOM inteiro sempre tem alguma frase de login/captcha em script/modal.
**Certo:** evidência antes de string (`capture._looks_blocked`: poucas imagens
**e** frase de bloqueio) e salvar print + HTML do bloqueio.

### R18. Persistência em cadeia
Uma etapa que falha leva as outras junto. **Certo:** cada artefato no seu
try/except; `manifest.json` sempre gravado no `finally`.

### R20. Afirmar o que o dado não diz
"Sem selo = 3P" carimbou 40% da SERP sem evidência. Aqui o equivalente é dizer
"pago" ou dar nome ao anunciante sem marcador. **Certo:** `Nao identificado`.

### R21. Dois `sync_playwright()` vivos na mesma thread
"Sync API inside the asyncio loop". **Certo:** `playwright_runtime.acquire()/release()`.

### R22. Chrome compartilhado morto tratado como bloqueio
A janela é do usuário e pode ser fechada. **Certo:** `get_local_browser()` cura o
singleton; nunca guardar contexto antigo; browser morto troca de caminho,
bloqueio encerra a URL.

### R25. Anúncio contaminando ranking
Na Magalu, anúncio (`ads=patrocinado`) entrava como posição orgânica. Aqui é o
inverso e vale o mesmo cuidado: **o que é pago precisa estar separado do
orgânico em toda métrica**.

## Parte 2 — aprendidos no Shelf Proof

### S1. Ler a home logada como se fosse a vitrine do mercado (11/11/2026)
**Errado:** analisar a home salva logado e concluir "ar-condicionado domina a
Amazon e o ML". **Por quê:** dezenas de vitrines "com base no seu carrinho",
"visto recentemente". Era o histórico do usuário. **Certo:** sessão anônima em
contexto novo (`new_isolated_context`) por padrão; persona é coleta separada.

### S2. Contar "Patrocinado" dentro de script (11/11/2026)
**Errado:** contar a palavra no HTML bruto (deu 17 na Amazon). **Certo:** remover
`script/style/noscript` antes (deram 16 = 4 blocos de marca + 12 produtos).

### S3. Tratar todo slot "oferta patrocinada" do Magalu como pago
**Errado:** o carrossel `desk_home_large_carrossel_p6_10` usa o mesmo texto de alt
para campanhas da própria Magalu (antecipadas, montagem, telefonia, entrega
rápida). **Certo:** pago só se o destino `/selecao/<slug>` contém uma marca;
sem marca = campanha do marketplace.

### S4. Clone de carrossel contado duas vezes
Carrosséis duplicam o primeiro/último slide para o loop infinito. **Certo:**
dedupe banner/display por (slot, destino). Produto patrocinado repetido em duas
vitrines **não** é clone: são duas posições compradas.

### S5. Visibilidade do slide do carrossel pela opacidade da própria imagem
**Errado:** `getComputedStyle(img).opacity` — a transparência fica no `<a>` pai, e
os 4 slides pareciam visíveis ao mesmo tempo. Também não serve `elementFromPoint`:
camada com opacidade 0 por cima "recebe" o ponto. **Certo:** multiplicar a
opacidade dos ancestores (`ELEMENTS_JS`), e casar peça escondida pelo `src`
mesmo assim (slide escondido também é peça).

### S6. Publicar peça com celebridade
Peças do 11.11 traziam artistas e apresentadores. **Certo:** revisão pela folha de
contato e `review.json` antes de publicar; o espaço pago continua no ranking.

### S7. Display sem anunciante no HTML
Amazon `adplacements:*` e parte do Mercado Ads não dizem quem pagou; o
"Sponsored Brands" da Neutrogena só tinha o logo na imagem. **Certo:** `Nao
identificado` + evidência "precisa da leitura visual" até a fase 3 (visão).

### S8. Imagem que o servidor não declara como imagem (12/11/2026)
**Sintoma:** no Windows o e2e saía com **0 imagens**. **Causa real:** o `http.server` do
teste usa o `mimetypes`, que no Windows lê o registro, e `.webp` saía como
`application/octet-stream`; o robô só aceitava `image/*`. (Primeiro suspeitamos do
`response.body()` dentro do handler de eventos: não era, mas ler o corpo depois ficou.)
**Certo:** aceitar `octet-stream` de requisição de imagem e decidir pelos primeiros bytes
(`capture.sniff_image_type`), porque CDN de verdade também erra o tipo; o handler só anota,
`flush()` lê os corpos, `fetch_missing()` busca de novo o que faltou, e falha vai para o manifest.

### S9. User-Agent fixo de outra versão do Chrome (12/11/2026)
**Errado:** UA "Chrome/131" no contexto de um Chrome 14x via CDP. O `navigator.userAgent`
contradiz os client hints (`Sec-CH-UA`) que o próprio navegador manda; a Magalu respondeu
**403 na primeira requisição**. **Certo:** desktop usa o UA real; mobile usa UA Android com a
versão do Chrome que está rodando (`capture.context_options`). É o R14 do RAC, agora pela versão.

### S10. Página de bloqueio que não parece bloqueio (12/11/2026)
**Errado:** a página do Akamai na Magalu ("Não é possível acessar a página (Erro 403)") não
tinha nenhuma frase conhecida, e a captura saiu "OK, 0 peças". **Certo:** o status HTTP da
página principal entra como evidência (`manifest.http_status`; 403/429 com pouca imagem =
bloqueio) e a frase da Magalu está em `BLOCK_PHRASES`.
