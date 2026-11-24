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

### S11. Contexto novo e vazio em site com Akamai (12/11/2026)
**Errado:** abrir a home da Magalu num `new_context()` (sem cookie, sem histórico) do
Chrome real: 403 já na primeira requisição, mesmo com rebrowser e UA real. Na mesma
janela, a home digitada à mão abria normal. **Certo:** `--session anon_warm` (ou
`"session": "anon_warm"` no `targets.json`): aba no perfil dedicado nunca logado,
aquecida na home até o `_abck` validar, como o RAC faz (`cdp_magalu_collection.md`).

### S12. Primeira marca do dicionário em título de produto (12/11/2026)
**Errado:** `find_brand` devolve a primeira marca **na ordem do dicionário**; em
"Notebook Lenovo LOQ ... Intel Core i5" deu **Intel**, e 4 notebooks Lenovo viraram
anúncio da Intel na Magalu. **Certo:** em título de produto, `find_brand_first` (a marca
que aparece primeiro no texto). O dicionário ordenado continua valendo para slug de campanha.

### S13. Link relativo no HTML x absoluto no navegador (12/11/2026)
**Errado:** casar peça e elemento só por `src`/`href` exatos. O card "Patrocinados" da Magalu
tem `href="/notebook-.../p/..."` no HTML e `https://www.magazineluiza.com.br/notebook-...`
no navegador; 11 peças pagas ficaram com área 0. **Certo:** guardar a imagem do card e,
sem ela, casar por host + caminho (`pipeline._path_key`), um elemento por peça.

### S14. Janela por cima da vitrine (12/11/2026)
**Errado:** fotografar a Shopee com o seletor "Selecione seu idioma" e o aviso de cookies
cobrindo o carrossel: frames e print mostram a janela, não a vitrine. **Certo:**
`capture.dismiss_overlays` clica, como um cliente, só em botões de nome exato
(`Português (BR)`, `Aceitar todos os cookies`, `Entendi`...) e grava em `manifest.dismissed`.
Nunca clicar em login, captcha ou "Configurações".

### S15. Mesma imagem com outro nome no navegador (12/11/2026)
**Errado:** casar a peça com a imagem baixada pelo endereço exato. A Shopee põe `<arquivo>` no
`<img src>` e o navegador baixa `<arquivo>@resize_w797_nl.webp`; o ML troca `D_NQ_2X_` por
`D_NQ_`. Resultado: 3 "Nao identificado" sem imagem, e a visão nem foi chamada. **Certo:**
`pipeline._src_key` (sem sufixo de tamanho e sem extensão) como segundo critério.

### S16. Rodar o Shelf Proof com o Python do RAC (17/11/2026)
**Errado:** terminal com o `.venv` do `rac-position-tracker` ativado; o venv do RAC não tem o
`lxml` e a 1ª rodada do celular capturou tudo e não classificou nada. **Certo:** venv próprio
(`scripts\instalar.bat` cria `shelf-proof\.venv`); os `.bat` usam `scripts\_python.bat`, que
escolhe esse venv mesmo com outro ativado, e o `event` confere os pacotes antes de abrir o Chrome.

### S17. Pesquisa num iframe e rolagem que não rola (Magalu celular, 17/11/2026)
**Errado:** a home do celular saiu com 1962 px e as vitrines (`lazyload-container`) vazias. A
pesquisa "Queremos o seu feedback" (QuestionPro) é um **iframe** por cima da home, carregado por
último: o robô só procurava botões na página principal, e a roda do mouse não moveu a página.
**Certo:** `dismiss_overlays` procura também nos iframes ("Agora não", nunca "Sim") e roda de novo
antes de rolar; `_human_scroll` rola por script quando a roda não mexe (`manifest.script_scrolls`).

### S18. `py -3` pegou um Python 32 bits (17/11/2026)
**Errado:** criar o venv com o primeiro Python 3 do PC: era 3.14 **32 bits**, o `greenlet` não
tinha pacote pronto e pediu o compilador C++. **Certo:** `scripts\instalar.bat` só aceita 64 bits
(prefere 3.13) e recria o `.venv` se ele for de 32 bits.

### S19. Celular e desktop no mesmo perfil (Magalu, 17/11/2026)
**Errado:** depois da captura do celular no perfil dedicado, o **desktop** da Magalu abriu em
`m.magazineluiza.com.br` (cookie de versão), vazio. **Certo:** o celular `anon_warm` guarda os
cookies do site antes e devolve ao fechar a aba (`snapshot_site_cookies`/`restore_site_cookies`);
se o desktop ainda cair em `m.`, a captura limpa os cookies do site, aquece de novo e tenta outra vez
(`manifest.mobile_redirect_fixed`).

### S20. `response.body()` sem tempo limite (17/11/2026)
**Errado:** ler o corpo de toda resposta de imagem anotada: numa resposta que nunca termina, a
captura da Magalu ficou 17 min parada. **Certo:** `flush()` só lê resposta terminada
(`request.timing.responseEnd`) e tem prazo; `fetch_missing()` tem prazo. O manifest guarda
`timings` (segundos por etapa) e `stage` (onde parou, se interromper com Ctrl+C).

### S21. Celular com identidade de Android na Magalu (17/11/2026)
**Errado:** emular o celular com UA e client hints de Android: a home abria, mas as consultas de
conteúdo (`federation.magazineluiza.com.br/graphql`: `showcaseQuery`, `adsItemsQuery`...) eram
barradas por **CORS** e todas as vitrines ficavam vazias (1962 px, 9 imagens). No navegador à mão,
com a janela estreita, vinha completa. **Certo:** na Magalu, `"mobile_emulation": "viewport"` no
`targets.json`: tela 412 px e toque de celular, navegador se apresentando como desktop (6535 px,
49 imagens, graphql 200). O Showroom avisa na metodologia. Teste A/B: `scripts\teste_celular_magalu.bat`.
**Conferido (17/11, rodada 5):** nessa tela os slots pagos são os de **desktop** (`desk_hypertop_Ads_small`,
`desk_home_Ads_large_carrossel_p3..p5`): layout de celular, anúncio escolhido para desktop. Os `msite_...`
só viriam com UA Android, que hoje esbarra no CORS.

### S22. `\b` em slug com sublinhado (17/11/2026)
**Errado:** `\btcl\b` não acha "tcl" em `tcl_tv_blackfriday26` (o `_` conta como letra para o `\b`),
e o banner do slot `desk_hypertop_Ads_small` virou campanha da Magalu. **Certo:** em marca que
aparece em slug, `(?<![a-z0-9])tcl(?![a-z0-9])`.

### S23. Regra presa ao domínio no link (Shopee, 17/11/2026)
**Errado:** exigir `shopee.com.br/m/` no `href`: a Shopee passou a usar links relativos (`/m/...`,
`/shop/<id>`) e a home inteira deu **0 peças**, sem erro nenhum. **Certo:** resolver o link contra o
domínio do site (`urljoin`) antes de casar, e desconfiar de "OK, 0 peças" num site que tinha peças.

### S24. Captcha da Shopee desktop no meio da rodada (17/11/2026)
**Visto:** 2 captchas em 3 rodadas na Shopee desktop (sessão anônima limpa), sempre com outros sites
antes; sozinha, abriu normal. **Certo:** nunca resolver captcha (regra 13). O `event` tenta **uma vez**
de novo, no fim da rodada e depois de 60–120 s, o que deu bloqueio; o bloqueio fica registrado
(`rounds.json`, `retry`). Se continuar, decidir com o dono se a Shopee entra no `anon_warm`.

### S25. Anúncio em iframe sem imagem (Amazon celular, 17/11/2026)
**Errado:** esperar `<img>` em todo espaço pago: os displays `adplacements:*` da Amazon vêm num iframe,
e 6 de 8 pagas "Nao identificado" ficaram sem imagem (sem Showroom, sem leitura visual). **Certo:** a
captura grava a caixa de cada espaço (`slots.json`) e o pipeline recorta o criativo do `full.jpg`
(`extra.image_source = "recorte do print da pagina"`); caixa em branco não vira criativo. Também:
link `/ap/signin` nunca é destino de anúncio (o card "Patrocinado" pegava o login do bloco ao lado).

### S22. Banner de marca no varejo especialista lido como mídia paga (24/11/2026)
**Tentação:** a home da Frigelar/Dufrio/Leveros na Black Friday é quase toda de marca (Midea, TCL, LG,
Daikin...), e o alt da Dufrio diz "Banner TCL Trade". Parece espaço comprado. **Por quê não:** nenhuma das
11 homes traz rótulo de patrocínio nem parâmetro de anúncio; verba de trade é acordo fora da página.
**Certo:** `marketplace` (banner da loja) com `extra.featured_brand` e a fonte da marca na evidência; o
"Trade" vira `extra.trade_hint` para conferir com a marca. Ranking próprio no Showroom ("Marcas em
destaque"), separado de "Quem pagou".

### S23. Deduplicar banner pelo link ou pelo caminho da imagem (24/11/2026)
**Errado:** tratar como clone de carrossel o banner com o mesmo destino (Poloar: 6 banners diferentes para
`/ar-condicionado?...`) ou com o mesmo caminho sem query (Poloar `/_next/image?url=...`, Frigelar
`/img?source=...`): a Frigelar perdia o mosaico da Gree e a Poloar ficava com metade das peças.
**Certo:** clone = mesmo slot + mesma imagem, ignorando só os parâmetros de tamanho (`_dedupe_specialist`);
no pipeline, `_src_key` lê o arquivo do parâmetro `url` do Next.js.

### S24. Só ver o que a regra do site conhece (25/11/2026)
**Errado:** peça só existia se uma regra por site a reconhecesse (carrossel, slot de anúncio). O Showroom
listava marca em destaque sem a peça, e pop-up de cupom, banner do meio da página, lateral e iframe de
rede de anúncio ficavam de fora. Pior: `dismiss_overlays` fechava janelas sem fotografar.
**Certo:** leitura da página como um cliente (`reading.py` + `creatives.json` + `popups/`): todo criativo
visível vira peça com a zona; pop-up é fotografado antes de fechar. Pago continua exigindo marcador.
**Cuidado já pago no ensaio:** widget de acessibilidade (VLibras) é camada fixa de tela cheia e
transparente; seletor de idioma da Shopee é janela utilitária; card de produto da Clima Rio tem o preço
longe da imagem no DOM (filtrar também por link `/p` e imagem `/arquivos/ids/`).

