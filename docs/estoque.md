# Estoque de camisetas

A janela principal tem três abas: **DTF** (o fluxo de sempre, sem mudanças), **Estoque de camisetas** e
**Estoque de estampas** (só mostra "Em breve").

Não mexe em licenças nem na API. Tudo é local.

## O que a aba mostra

| Área | O que é |
|---|---|
| **Estoque** | Quantidade de cada cor × tamanho. Começa em 0. Dois cliques na célula para editar (inteiro ≥ 0). |
| **Futuro** | O que os pedidos importados vão consumir (calculado a partir da planilha). |
| **Saldo total** | Estoque − Futuro. Negativo fica em vermelho. |
| **Separação** (à direita) | Cada cor/tamanho do pedido: precisa, estoque (✓ quando cobre, ✗ vermelho quando falta; o mouse sobre o ✗ mostra "Faltam N") e a marca "separado". |
| **Pendentes** | Itens que ficaram fora da conta (veja "Janela de validação"). Aparecem destacados com um aviso. |

Botões: **Nova cor**, **Novo tamanho** (nome obrigatório; duplicado é recusado ignorando maiúsculas, acentos e
espaços extras), **Adicionar estoque em massa** (quantidade, cor "todas" ou uma, tamanhos "todos" ou
selecionados, com confirmação mostrando o que muda), **Excluir cor** e **Contagem rápida**.

Cores iniciais: Preta, Marrom, Bege, Branca. Tamanhos: P, M, G, GG. Equivalências iniciais: "preto" = Preta e
"branco" = Branca.

## Como o futuro é calculado

Ao importar a planilha na aba DTF, o app lê cada item e identifica **cor** e **tamanho(s)**. Não existem colunas
separadas de cor e tamanho na planilha da UpSeller: tudo vem na coluna **Variação** (e, para a cor, às vezes no
**SKU**).

Formatos reconhecidos (maiúsculas, acentos e espaços duplos não importam):

| Variação | Resultado |
|---|---|
| `Preta,G` | 1 × Preta G |
| `Preto,M - G` | kit: 1 × Preta M e 1 × Preta G por unidade do pedido |
| `G - GG,Preto` | cor no fim: Preta G e Preta GG |
| `Kit Bege,P - G` | `Kit` é ignorado: Bege P e Bege G |
| `Kit Preto, GG - GG` | 2 × Preta GG por kit |
| `Marrom - Estampa Preta,P - G` | Marrom. **A cor depois de "Estampa" é da estampa, nunca da camiseta** |
| `P - M`, `GG` (sem cor) | procura a cor no SKU; se não achar, vai para a janela de validação |

- A quantidade do pedido **multiplica**: 3 × `Preto,M - G` somam 3 em Preta M e 3 em Preta G.
- Uma variação com um só tamanho é 1 camiseta.
- Cor no SKU: um trecho do SKU (separado por `-`, `_`, `/` ou `|`) igual a uma cor cadastrada, por exemplo
  `SOLO - DOCTOR DOOM-PRETO-M`. Se houver mais de uma cor diferente, não adivinha.
- Duas cores em que não dá para saber qual é a da camiseta: não reconhecido.
- **Cada importação SUBSTITUI o futuro** (nunca acumula). O futuro sai dos pedidos carregados no projeto, inclusive
  os já montados no rolo.
- Linhas idênticas repetidas no mesmo pedido são somadas (como a planilha faz) e o app avisa quantas foram.

Os nomes são comparados normalizados (minúsculas, sem acento, sem espaços extras). As equivalências ficam salvas
no banco (por exemplo "preto" = Preta) e são aprendidas na janela de validação; não há tela para editá-las.

## Janela de validação (itens sem cor ou tamanho)

Se algum item não tiver cor reconhecida (nem na Variação nem no SKU), ou nenhum tamanho reconhecido, abre uma
janela **antes** de calcular o futuro. Se tudo for reconhecido, ela não aparece.

- Itens com o mesmo SKU (ou, sem SKU, o mesmo anúncio e variante) aparecem numa linha só, com anúncio, SKU,
  Variação, tamanhos e a quantidade total de camisetas afetadas.
- Cada linha tem um seletor de cor (com **Nova cor...**) e, quando falta tamanho, dois seletores de tamanho
  (o segundo é para kit). **Aplicar a todos os iguais** copia a escolha para as linhas do mesmo SKU.
- **Lembrar para este SKU** (marcado por padrão) grava SKU → cor para as próximas importações. **Nunca** se grava
  um mapeamento só pelo texto da Variação (um `P - M` pode ser de cores diferentes). Sem SKU, vale só para esta
  importação. Um texto de cor desconhecido (por exemplo "verde") vira uma equivalência por texto, pois é um nome
  de cor.
- **Confirmar** (só habilita com tudo preenchido) calcula o futuro. **Deixar pendentes** continua sem preencher
  algumas linhas: elas ficam fora da conta e aparecem destacadas na aba. **Cancelar** não altera o futuro atual.

## Finalizar pedido

Botão **FINALIZAR PEDIDO** na aba DTF, abaixo de "Exportar documento". Fica desabilitado quando não há futuro e
durante a operação (não aceita clique duplo).

1. Mostra um resumo (cor, tamanho, futuro, estoque, depois, faltam).
2. Se algum item tem futuro maior que o estoque, ou se há pendentes, lista e exige marcar
   "Entendo e quero finalizar mesmo assim".
3. Ao confirmar: desconta o futuro do estoque (**nunca negativo**: vai a 0 e a falta fica no histórico), zera o
   futuro, as marcas de "separado" e os pendentes. Tudo numa única transação.

O "Finalizar pedido" é independente de "montar rolo" e do histórico de lotes.

## Proteção contra abate em duplicidade

Antes de processar uma planilha o app confere duas coisas e, se for o caso, mostra **uma** janela:

**A) Pedidos já finalizados.** Ao finalizar, os números de pedido da plataforma que foram abatidos ficam
registrados com a data. Na importação seguinte, os pedidos carregados que já constam como finalizados
**ficam fora do futuro** por padrão ("N pedidos já foram finalizados no estoque em DD/MM"), com uma opção na mesma
janela para incluí-los de novo. Os pedidos continuam carregados no projeto; só não entram na conta do estoque.

**B) Planilha repetida.** Cada importação guarda data/hora, nome do arquivo, hash SHA-256, os números de pedido e
se já foi finalizada. Se o arquivo tem o mesmo hash de uma importação anterior, **ou** mais de 80% dos pedidos já
constam em importações anteriores (exportação nova da UpSeller com outro nome), aparece:
"Esta planilha parece já ter sido importada em DD/MM às HH:MM (N pedidos). Estado: finalizada no estoque /
ainda não finalizada."

Botões: **Cancelar importação** (cancela tudo, o projeto e o estoque ficam como estavam), **Importar mesmo assim** e,
quando há pedidos novos misturados com antigos, **Importar só os pedidos novos**. Se a importação anterior já foi
finalizada, o botão padrão é Cancelar.

Também aparece o aviso "N pedidos já foram montados antes" (do histórico de lotes). Eles continuam contando.

## Histórico

Os movimentos (sem botão na tela; ficam gravados no banco): movimentos com data e hora, tipo (ajuste manual, adição em massa, importação, finalização),
cor, tamanho, quantidade, antes e depois, com filtro por tipo; e uma segunda aba com as planilhas importadas.
Movimentos de importação mostram o **futuro** (marcado "(futuro)"); os demais mostram o **estoque**.

## Onde os dados ficam

Mesmo banco SQLite do app (`dtf_manager.db`, em `AppLocalData`), em tabelas novas `stock_*`, gravadas em transação.
Sobrevivem a fechar o app.

**Cópia de segurança:** na primeira vez que o app abre uma versão com estoque sobre um banco já existente, ele copia
o banco para `dtf_manager.db.antes-do-estoque.bak`, na mesma pasta, **antes** de criar as tabelas novas. A cópia é
feita uma única vez e nunca é sobrescrita. As tabelas antigas não são alteradas.

Tabelas: `stock_colors`, `stock_sizes`, `stock_levels`, `stock_future`, `stock_aliases`, `stock_sku_colors`,
`stock_pending`, `stock_movements`, `stock_imports`, `stock_finalized_orders`, `stock_state`.

## Código

| Arquivo | Papel |
|---|---|
| `dtf_manager/utils/stock_names.py` | normalização de nomes |
| `dtf_manager/services/stock_parser.py` | lê cor e tamanhos da Variação/SKU (texto puro) |
| `dtf_manager/services/stock_repository.py` | SQL do estoque |
| `dtf_manager/services/stock_service.py` | regras: saldo, massa, futuro, finalizar, duplicidade |
| `dtf_manager/core/stock_controller.py` | decide e orquestra; a UI não chama serviços |
| `dtf_manager/ui/pages/stock_tab.py` | aba (só exibe e emite sinais) |
| `dtf_manager/ui/widgets/stock_dialogs.py` | diálogos e `StockPrompts` |

Testes: `tests/test_stock_service.py` (regras, sem Qt) e `tests/test_stock_ui.py` (controller, diálogos, janela).

## Layout da aba e exclusão de cor

- Cada cor é uma **caixinha de bordas arredondadas**, com um pequeno espaço entre uma e outra. Dentro dela ficam os
  tamanhos um abaixo do outro (P, M, G, GG), cada um com Estoque, Futuro e Saldo. No fim há uma única caixa
  "TOTAL GERAL".
- **Excluir cor** (botão ao lado de "Nova cor"): pergunta qual cor e pede confirmação, dizendo quanto estoque e
  futuro serão descartados. Remove a cor, o estoque e o futuro dela, os mapeamentos SKU → cor e as equivalências que
  apontavam para ela. O que ela tinha vira "Ajuste manual" para 0 no histórico (nota "Cor excluída"), e os
  movimentos antigos continuam lá. Dá para cadastrar a cor de novo depois.
- **Janela de validação:** mostra a imagem do produto (o link `Link da Imagem` da planilha, baixado em segundo plano;
  sem imagem aparece "sem imagem") e pergunta só a **cor**. Os seletores de tamanho só aparecem quando alguma linha
  não tem tamanho legível.

## Cartão "Operação em andamento": Cancelar e Finalizar

Além de **Continuar**, o cartão tem dois botões:

- **Cancelar:** descarta o trabalho daquela planilha. Pede confirmação, tira os pedidos do projeto, apaga a operação
  salva e zera o futuro e os pendentes dela. O estoque **não muda**. O registro daquela importação também é apagado,
  então dá para carregar a mesma planilha de novo, sem aviso de "já importada", e começar do zero. O histórico
  registra o futuro zerado como "Operação cancelada". Se a importação já tinha sido finalizada, o cancelamento não
  desfaz nada e os pedidos continuam protegidos.
- **Finalizar:** dá baixa no estoque de camisetas e zera o futuro (mesmo resumo e confirmação do botão
  "Finalizar pedido"), e encerra a operação: ela some do cartão e os pedidos saem do projeto. Se não houver nada no
  futuro, pergunta se deseja encerrar mesmo assim.

As abas (DTF, Estoque de camisetas, Estoque de estampas) ficam centralizadas no topo da janela.

# Estoque de estampas

A terceira aba, **Estoque de estampas**, controla quantas cópias de cada arte (arquivo de imagem) existem em estoque
e quantas o pedido importado vai usar. Mesmo layout da aba de camisetas: três cartões no topo, a lista à esquerda e a
**Separação** à direita.

## A lista da esquerda

- Mostra **todas** as artes da **Pasta das artes** escolhida na aba DTF (busca recursiva; png, jpg, jpeg e webp).
  A listagem é leve: só pela extensão, sem abrir cada imagem (o `scan_art_directory` da vinculação automática não
  foi alterado). Uma imagem corrompida aparece sem miniatura, com um aviso discreto.
- Colunas: **Imagem**, **Arquivo**, **Estoque** (inteiro ≥ 0, editável na célula; Tab/Enter/Esc como na aba de
  camisetas), **Futuro** e **Saldo** (= Estoque − Futuro; vermelho quando negativo, zero apagado).
- **Cada arte aparece uma única vez.** A identidade da arte é o **arquivo**: o caminho relativo dentro da pasta
  selecionada. SKUs, variações e tamanhos diferentes que usam a mesma imagem **somam** no mesmo registro; nunca há
  linha por SKU ou tamanho. Artes vinculadas manualmente a um arquivo **fora da pasta** entram com chave pelo
  caminho absoluto e a marca "fora da pasta".
- Busca pelo nome do arquivo (sem acento, sem diferenciar maiúsculas) e filtros **Só com futuro** e **Só com falta**.
- Cartões: **Total em estoque**, **Total no pedido** (soma do futuro) e **Faltam** (`X de Y`, vermelho quando X > 0).
- Se a pasta muda ou é atualizada, a lista é atualizada (também ao abrir a aba). Um arquivo que **sumiu** da pasta
  mas tem estoque registrado fica marcado "arquivo não encontrado" e **nunca é apagado do banco**.

### Miniaturas

Carregadas sob demanda: só as linhas visíveis (mais uma margem) são pedidas, por threads em segundo plano, lendo a
imagem já reduzida (`QImageReader`), com cache LRU em memória. A interface não trava mesmo com centenas de
imagens. Quem falha ao carregar fica registrado e não é tentado de novo.

### Arquivos com conteúdo idêntico

Em segundo plano, com prioridade baixa e **só depois** de a lista aparecer (1,5 s), o app procura arquivos com o
mesmo conteúdo e nomes diferentes. Só os de mesmo tamanho são comparados por hash SHA-256, com cache por
(caminho, tamanho, data). O resultado é um aviso discreto; **nada é unido**.

### Mover estoque (renomeações e trocas de pasta)

- **Mover estoque para outro arquivo:** escolhe o arquivo de origem (com estoque) e o de destino; pede confirmação
  e move todo o estoque. As duas pontas entram no histórico.
- **Sugerir correspondências** (só aparece quando há arquivo "não encontrado" com estoque): propõe pares pelo
  **mesmo nome de arquivo** (nomes que casam com mais de um arquivo ficam de fora). Você marca um a um ou todos e só
  então o estoque é movido. Nunca move sozinho.

## O futuro das estampas

Vem da planilha importada, **depois** da vinculação item → arte (automática, manual ou memória de vínculos):

- Cópias por item = `quantidade do pedido × copias_per_product` de cada arte vinculada, **a mesma fórmula** da
  montagem do rolo (`art_copies`, usada por `build_dtf_print_plan` e por `count_art_copies`). Tamanhos de camiseta
  não entram na conta; um kit é uma lista de artes (ou `copies_per_product` maior). O rolo mantém o mesmo arquivo em
  dimensões diferentes como entradas separadas; o estoque **soma por arquivo**, ignorando dimensões.
- É **recalculado toda vez que os vínculos mudam**, sempre **substituindo** (nunca acumulando). No histórico entra só
  o **resultado líquido** de cada recálculo: uma linha por arte cujo futuro mudou, não uma por vínculo.
- Usa a **mesma lista de pedidos contados** do estoque de camisetas: planilha repetida e pedidos já finalizados
  são tratados pelas mesmas proteções (a janela de aviso da importação vale para os dois).
- Itens **sem arte vinculada** ficam fora da conta, aparecem no aviso "N itens sem arte vinculada" com o atalho
  **Abrir vinculação manual** e não bloqueiam nada.
- As marcas de "separado" sobrevivem aos recálculos e são zeradas por uma nova importação.
- Se os pedidos carregados não são os da importação atual do estoque (por exemplo, a validação foi cancelada), o
  recálculo não mexe no futuro.

## Separação (direita)

Uma linha por arte que aparece na planilha: miniatura, arquivo, **Usada** (o futuro), **Estoque** (✓ quando cobre
tudo; ✗ vermelho quando falta, com a dica "Faltam N") e a caixa **Separado**. Estado vazio centralizado. O botão
**Copiar lista do que falta** copia o arquivo e a quantidade que falta; fica desabilitado quando não falta nada.

## Finalizar pedido

O botão existente passa a abater **camisetas e estampas na mesma transação**: ou grava as duas partes ou nenhuma.
O resumo é único (camisetas e estampas); itens com falta, em qualquer das duas, exigem a confirmação explícita. O
estoque nunca fica negativo (limita em 0 e registra a falta no histórico) e depois o futuro de estampas e as marcas
de "separado" são zerados. **Cancelar** a operação zera os dois futuros e não mexe nos estoques. Também funciona
quando só as estampas têm futuro.

## Histórico e banco

- Cada movimento de estampa (ajuste manual, importação/recálculo, finalização, mover estoque) entra no mesmo
  histórico, com data e hora, arquivo (na coluna **Cor / Arquivo**), quantidade, antes e depois. A coluna **Produto**
  distingue Camiseta de Estampa.
- Migração **aditiva** no mesmo SQLite: tabelas novas `stock_art_files`, `stock_art_levels`, `stock_art_future` e
  `stock_art_hashes`, e a coluna `produto` (padrão `camiseta`) em `stock_movements` por `ALTER TABLE ... ADD COLUMN`.
  Nada existente é alterado.
- **Cópia de segurança:** antes da migração o banco é copiado ao lado como `dtf_manager.db.antes-das-estampas.bak`
  (uma vez só, sem sobrescrever; a primeira cópia, `.antes-do-estoque.bak`, continua valendo para quem vem de antes
  do estoque de camisetas).

## Código

| Arquivo | Papel |
|---|---|
| `dtf_manager/services/art_folder_listing.py` | listagem leve da pasta |
| `dtf_manager/services/art_stock_repository.py` / `art_stock_service.py` | SQL e regras (uma arte por arquivo, futuro, finalizar, mover) |
| `dtf_manager/services/art_duplicates.py` | arquivos idênticos (hash só dos de mesmo tamanho) |
| `dtf_manager/services/thumbnail_cache.py` | miniaturas preguiçosas e a varredura de idênticos em segundo plano |
| `dtf_manager/services/print_plan_service.py` | `art_copies` e `count_art_copies` |
| `dtf_manager/core/art_stock_controller.py` | decide; a UI não chama serviços |
| `dtf_manager/ui/pages/art_stock_tab.py` | a aba |
| `tests/test_art_stock.py`, `tests/test_art_stock_ui.py` | testes |

## Artes adicionadas à mão no rolo

Uma arte adicionada manualmente no rolo ("Adicionar arte") também entra no **futuro** do estoque de estampas, com a
quantidade do cartão (somada às cópias vindas dos pedidos, se for o mesmo arquivo). Alterar a quantidade ou excluir o
cartão atualiza o futuro. Cartões montados a partir dos pedidos **não** são contados duas vezes. Ao finalizar ou cancelar,
essas cópias são baixadas/zeradas junto e os cartões deixam de contar como "manuais".

## Rolo e lista de artes

Duplo clique num cartão da lista de artes seleciona e centraliza no rolo as cópias daquela arte; clicar numa arte no
rolo destaca o cartão dela na lista. O rolo ocupa toda a altura disponível, até o rodapé.
