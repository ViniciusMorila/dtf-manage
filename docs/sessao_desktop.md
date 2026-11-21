# Sessão persistente do desktop — etapa 2

> **Atualização (licenças):** a validação de licença, o ID da máquina, o timer
> periódico e a carência offline estão em [licencas_desktop.md](licencas_desktop.md).
> Este documento descreve apenas a sessão. As partes abaixo que citam
> `/license/status`, `active`/`ACTIVE` ou a ausência de timer foram substituídas:
> a licença vem de `GET /licencas/status` (`status == "ATIVA"`) e há validação a
> cada 1 hora.

Esta etapa usa os contratos fornecidos para a API. Não modifica o servidor,
o SQLite operacional, importações, estoques ou exportações.

## Armazenamento

`SessionStorage` encapsula Windows Credential Manager via `pywin32-ctypes`.
A biblioteca está registrada explicitamente em `requirements.txt`, embora
já fosse instalada neste ambiente pelo PyInstaller. Não usamos seleção automática
de backends, `keyring`, arquivos de tokens ou fallback em texto puro.

Existe uma única credencial genérica, com alvo `DTF Manager/session/production`
(ou `DTF Manager/session/dev-<hash>` quando `DTF_API_URL` aponta para outra API;
o alvo não depende mais da URL de produção). O identificador da credencial é
`desktop-refresh-token`. A credencial antiga, que levava a URL no nome, não é
migrada.
`CredWrite` substitui o valor existente em uma chamada, sem arquivar A.
`CRED_PERSIST_LOCAL_MACHINE` mantém a credencial entre sessões do mesmo usuário
Windows, sem solicitar roaming. Senha e access token não são persistidos.

A proteção é a do usuário Windows: outros processos autorizados no mesmo perfil
podem ter acesso ao Credential Manager. Não há isolamento contra um perfil
Windows comprometido. Os testes não leem nem escrevem credenciais reais.

Uma trava `QLockFile` na pasta temporária do usuário impede duas instâncias
deste desktop de rotacionar a mesma credencial. A trava não contém tokens;
contém apenas os metadados de processo usados pelo Qt. Ao fechar, é liberada.

## Login, restauração e renovação

- Sem refresh salvo, mostra o formulário de login.
- Login: POST `/auth/login` com `email`, `senha` e `id_maquina`; salva refresh
  protegido; publica access apenas em memória; consulta `GET /licencas/status`
  (com `X-Id-Maquina`); constrói MainWindow apenas com `status == "ATIVA"`.
- Com refresh salvo, chama POST `/auth/refresh` com
  `{"refresh_token": "<token atual>", "id_maquina": "<id>"}`, sem Bearer nem cookies. A abertura
  automática válida não constrói LoginWindow. O formulário é criado somente
  quando necessário: ausência de sessão, falha, licença negada ou logout.
- Valida access, refresh, tipo bearer e `expires_in`. No refresh exige um
  sucessor diferente do token enviado. Salva B antes de liberar a sessão.
- Depois da gravação, sempre consulta licença com o novo access. Uma renovação
  em uso reaproveita a janela existente após autorização.
- `AuthService.refresh_session()` é o mecanismo central para futuros fluxos
  autenticados: consumidores aguardam `authenticated` ou `failed`. Solicitações
  concorrentes compartilham a mesma renovação; não disparam outro HTTP.
- Há um `QTimer` de **1 hora** que valida a licença com a janela aberta. Quando o
  access token expirou (401), o controller renova a sessão com o `id_maquina` e
  repete a consulta uma única vez. A restauração na abertura continua automática.

Fechar normalmente limpa memória e cancela replies, mas não apaga refresh
protegido e não chama logout.

O bootstrap preserva uma única QApplication e a identidade Qt antes de acessar
QSettings/QStandardPaths. A UI operacional é importada após licença ACTIVE;
esse import permanece incluído na duração de construção da MainWindow.

## Erros e limite inevitável da rotação

- Refresh 401/422 (`INVALID_REFRESH_TOKEN`): apaga a credencial e o cache da
  licença e apresenta login, explicando que a sessão pode ter sido encerrada por
  um login em outro computador (sessão única), bloqueio ou reset.
- Refresh 403/404/409 (`MAQUINA_DIFERENTE`, `LICENCA_EXPIRADA`, ...): não consome
  nem apaga o token (contrato). Licença vencida abre a tela de chave.
- 500/503, DNS, timeout ou conexão: preserva o token salvo. Com cache válido o
  app entra na carência offline de 72 horas; sem ele permite uma nova tentativa
  manual ou voltar ao login. Entrar novamente cria outra sessão,
  sem prometer revogar a anterior.
- Resposta 200 inesperada: não sobrescreve armazenamento e bloqueia reutilização
  de A nesse processo, pois o servidor pode já ter rotacionado. Exige login.
- Falha ao salvar B: não publica sessão; limpa memória, tenta apagar a credencial
  anterior e apresenta login. Não existe fallback inseguro.
- Falha de leitura/exclusão do Credential Manager: informa erro local, sem
  mostrar a exceção interna nem declarar que a exclusão aconteceu.

Sem grace period, uma queda entre a rotação no servidor e a gravação local
de B pode exigir novo login. O mesmo vale para uma resposta perdida ou fechamento
com refresh em andamento. Não existe recuperação de B pelo desktop.

## Logout

O botão "Sair da conta" fica na barra inferior. Respeita a confirmação existente
para vinculação não salva e aguarda o término da exportação antes de iniciar.
Só uma saída é enviada por vez. Se houver refresh em andamento, espera B e
envia logout com B, sem abrir/publicar uma nova sessão durante a saída.

POST `/auth/logout` usa JSON `{"refresh_token": "<token mais recente>"}`,
sem Bearer nem cookies. HTTP 200 com `{"status": "ok"}` confirma revogação do
refresh. O desktop apaga a credencial, limpa memória, fecha a janela principal
e mostra login. A API não invalida imediatamente access já emitidos.

Em erro remoto, a saída não é declarada confirmada. O usuário pode manter a
sessão e tentar depois, ou escolher sair apenas neste computador. Essa escolha
apaga somente o estado local e informa que a revogação remota não foi confirmada.
Respostas atrasadas são invalidadas por geração, sem salvar ou restaurar tokens.

## PyInstaller

O módulo contém import explícito de `win32ctypes.pywin32.win32cred`.
O PyInstaller instalado possui `hook-win32ctypes.core.py`, que coleta os
backends dinâmicos `ctypes` e, quando disponível, `cffi`. Não precisamos de
hook de keyring, metadados de keyring ou hidden imports adicionais no build atual.

Antes do próximo build, instale `requirements.txt` no ambiente usado para
empacotar. Preserve os hooks padrão do PyInstaller. Não foi reconstruído o
executável distribuído; o teste de empacotamento desta etapa faz apenas Analysis
de imports, sem PYZ/EXE/COLLECT. Testar o executável final continua necessário
quando o próximo build de distribuição for autorizado.

## Teste manual

No PowerShell, na raiz do projeto:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

1. Faça login com uma conta real com licença ativa. A janela principal deve abrir.
2. Feche pelo X, abra novamente e confirme a restauração sem digitar senha.
3. Repita o fechamento/abertura para exercitar a rotação de refresh.
4. Clique em "Sair da conta" e confirme retorno ao login; reabrir deve pedir login.
5. Com sessão salva, desconecte a rede e abra. A mensagem deve permitir tentar
   novamente; o token não deve ser apagado por essa falha. Reconecte e tente.
6. Durante logout sem rede, escolha saída local; confirme o aviso de revogação
   não confirmada e que a próxima abertura apresenta login.
7. Com uma instância aberta, inicie outra: ela deve bloquear autenticação e
   informar que o DTF Manager já está aberto.
8. Valide o cancelamento de logout com vinculação não salva e o bloqueio durante
   exportação. Nunca inspecione/imprima o conteúdo das credenciais.

Os passos acima fazem chamadas reais somente quando executados manualmente.
Os testes automatizados usam clientes, tokens e armazenamento simulados.

## Diagnóstico opt-in

Somente `DTF_AUTH_TIMING=1` ativa logs com nomes fixos de etapas e duração em
milissegundos. Sem a variável, os diagnósticos não consultam `perf_counter`,
não criam objetos Qt e não imprimem dados. Não há timers periódicos de
diagnóstico, sondas de event loop ou threads de monitoramento.

As métricas mantidas cobrem bootstrap, login/refresh HTTP, acesso à credencial,
licença, import operacional, construção/pintura da janela.
As métricas internas são aninhadas; não devem ser somadas novamente ao total.
`main_window_usable` marca o primeiro retorno ao event loop após a pintura.

```powershell
$env:DTF_AUTH_TIMING = '1'
.\.venv\Scripts\python.exe -u app.py
# Após fechar o aplicativo:
Remove-Item Env:DTF_AUTH_TIMING
```

Nunca são registrados senha, tokens, Authorization, conteúdo de credenciais,
corpos HTTP ou caminhos de imagens. A instrumentação não cria arquivos de log.
