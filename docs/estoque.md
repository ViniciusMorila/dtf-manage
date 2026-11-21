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
selecionados, com confirmação mostrando o que muda), **Excluir cor**, **Contagem rápida** e **Histórico**.

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

Botão **Histórico**: movimentos com data e hora, tipo (ajuste manual, adição em massa, importação, finalização),
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
