# Licenças no desktop

Este documento descreve como o DTF Manager valida a licença do usuário. O
contrato da API é o `docs/API_LICENCAS.md` do projeto `dtf-manager-api`; onde
este documento diverge dele, a divergência está marcada como **decisão do app**.

## Visão geral

- A licença pertence à conta, fica presa a **uma máquina** (`id_maquina`) e ao
  telefone do cadastro. Planos: `TESTE` (7 dias), `MENSAL`, `SEMESTRAL`, `ANUAL`
  e `VITALICIO`.
- Quem decide é sempre o **servidor**. O app só libera o uso com HTTP 200 e
  `status == "ATIVA"` em `GET /licencas/status`, exceto na carência offline
  (abaixo).
- As rotas antigas de assinatura (`GET /license/status` e `GET /me`) não são mais
  chamadas.

## Rotas usadas

| Rota | Quando |
| --- | --- |
| `POST /auth/register` | Tela "Criar conta". Cria a conta e o teste de 7 dias, ou, com `chave_ativacao`, a conta já com o plano da chave. Não devolve tokens; o app faz o login em seguida. |
| `POST /auth/login` | Envia `email`, `senha` e `id_maquina`. |
| `POST /auth/refresh` | A cada abertura e quando o access token expira. Envia `refresh_token` e `id_maquina`. |
| `GET /licencas/status` | A cada abertura e a cada 1 hora. Cabeçalhos `Authorization: Bearer` e `X-Id-Maquina`. |
| `POST /licencas/ativar-chave` | Com Bearer (renovação) ou com `email` e `senha` (licença vencida, sem sessão). |
| `POST /auth/logout` | Botão "Sair da conta". |

## ID da máquina

Arquivo: `dtf_manager/services/machine_id.py`.

- Lido por `ctypes`, sem processo externo: `GetSystemFirmwareTable` (SMBIOS) para
  o serial da placa-mãe, o UUID do sistema e o ID do processador, e
  `DeviceIoControl` para o serial do disco do sistema. Nenhum exige administrador.
- Valores genéricos são descartados (`To be filled by O.E.M.`, `Default string`,
  `None`, zeros, `FFFF…` etc.). São exigidos **pelo menos 2 componentes válidos**.
  Se não houver, o app recusa e pede suporte. Nunca usa MAC nem o `MachineGuid` do
  Windows, então o ID sobrevive à formatação.
- O ID é `SHA-256(sal fixo + componentes)` em hexadecimal de 64 caracteres,
  calculado uma vez por processo. Os números de série nunca são enviados nem
  gravados.
- O conjunto de componentes válidos faz parte da identidade: trocar a placa-mãe,
  o processador ou o disco do sistema muda o ID, e o administrador precisa
  resetar a máquina no servidor (o contrato limita a 3 resets em 12 meses).

## Cache local da licença

Arquivo: `dtf_manager/services/license_store.py`.

Guarda plano, status, expiração, `servidor_agora` e o momento da última
validação, protegidos com **DPAPI** (`CryptProtectData`, escopo do usuário
Windows) usando o ID da máquina como entropia. O arquivo `license_cache.bin` fica
na pasta de dados locais do app. Copiá-lo para outro computador ou usuário o
torna ilegível.

O cache serve apenas para **exibir informações e contar a carência de 72 horas**.
Ele nunca libera o uso fora da carência.

## Validação periódica

- A cada abertura: refresh (com `id_maquina`) e depois `GET /licencas/status`.
- Durante o uso: um `QTimer` consulta o status **a cada 1 hora** (mesmo intervalo
  em `LICENSE_CHECK_INTERVAL_MS`). Se o access token expirou (401), o app renova
  com o `id_maquina` e repete **uma vez**. Um segundo 401 bloqueia e pede login.
- Se a licença deixar de valer durante o uso (`LICENCA_EXPIRADA`,
  `LICENCA_BLOQUEADA`, `MAQUINA_DIFERENTE` etc.), o app **salva a operação ativa
  automaticamente**, mostra o aviso e só então bloqueia a janela principal. Não há
  perda de trabalho: o trabalho fica salvo e volta quando a licença é reativada.
- Recusas do refresh (403/404/409) não consomem nem apagam o refresh token, como
  manda o contrato. `INVALID_REFRESH_TOKEN` apaga o token e o cache.

## Carência offline de 72 horas

**Decisão do app.** O contrato da API recomenda o contrário: "o app nunca deve
liberar o uso diante de erro ou falha de rede". A carência foi adotada para não
parar uma produção por causa de uma queda de internet ou da API.

Regras (`dtf_manager/services/offline_grace.py`):

- Só vale quando a API está **inacessível**: falha de rede, timeout ou erro 5xx
  **sem** código do contrato. Uma recusa do servidor (qualquer `error.code`,
  inclusive `LICENCA_INDISPONIVEL` e `AUTHENTICATION_UNAVAILABLE`) **nunca**
  libera o uso e apaga o cache quando a licença é recusada.
- Conta **72 horas desde a última validação bem-sucedida**, usando a data do
  servidor (`servidor_agora`) avançada pelo relógio local. A licença em cache
  também precisa estar `ATIVA` e dentro da validade.
- Enquanto está em carência, a barra de status mostra, em destaque, o aviso
  "Modo offline: licença não validada" com o tempo restante. A cada hora o app
  tenta voltar a validar.
- Fora da carência, o app exige conexão.

### Relógio atrasado

O relógio do Windows é tratado como não confiável. A carência **não é contada**
(exige conexão) quando:

1. o relógio atual é anterior ao **maior horário local já observado** pelo app
   (marca persistida no cache, com tolerância de 5 minutos); ou
2. o relógio atual é anterior à **última data do servidor** em mais de 10 minutos; ou
3. no mesmo processo, o relógio local andou menos que o **relógio monotônico**
   (`time.monotonic`) em mais de 5 minutos, o que indica que o relógio foi voltado
   enquanto o app estava aberto.

O monotônico não sobrevive a um reinício do Windows. Por isso a marca de maior
horário observado fica no cache protegido. Adiantar o relógio apenas encerra a
carência mais cedo.

## Telas

- **Login**: "Criar conta" e "Tenho uma chave".
- **Criar conta**: nome, telefone (máscara brasileira e validação: celular
  DDD + 9 + 8 dígitos, fixo DDD + 8 dígitos começando em 2 a 5; aceita `+55`),
  e-mail, senha (mínimo 8, com letra e número) e confirmação. O servidor valida de
  novo. `cpf` e `plan_code` não são enviados. Veja "Criar conta com chave de
  ativação" abaixo.
- **Licença vencida / fim do teste / Tenho uma chave**: e-mail, senha e chave.
  Tem o botão **"Assinar"** (abre a tela de planos). Se o teste terminou, o título
  é "Fim do período de teste". Com sessão válida (licença que venceu durante o
  uso) pede só a chave. O botão "Ver planos no site" (`DTF_PAYMENT_URL`) só
  aparece se essa variável estiver configurada.
- **Assinar** (tela de planos): ver "Assinatura pelo WhatsApp" abaixo.
- **Renovação antecipada**: menu **Conta → Renovar licença (inserir chave)...**.
  Usa o Bearer e soma a duração à validade atual.
- **Barra de status**: plano e dias restantes. No teste, destaque com os dias que
  faltam; com 7 dias ou menos, aviso discreto e o botão **"Assinar"**.
- **Sair da conta**: apaga o refresh token e o cache da licença. O ID da máquina
  é calculado do hardware, então continua o mesmo.

Textos de erro são do app, em português, por `error.code`
(`services/error_messages.py`), com fallback para o `error.message` da API. O
`Retry-After` do 429 vira "Aguarde N minutos".

## Criar conta com chave de ativação

A tela "Criar conta" tem a opção **"Já tenho uma chave de ativação"**. Ao marcar,
aparece o campo da chave, com máscara `XXXX-XXXX-XXXX-XXXX` (maiúsculas, hífens
automáticos) e validação de formato antes de qualquer chamada: 16 caracteres do
alfabeto das chaves (não existem `0`, `1`, `I`, `L`, `O` e `U`). O botão passa a
dizer "Criar conta e ativar chave". Com a chave preenchida, o cadastro envia
`chave_ativacao` (contrato: `docs/API_LICENCAS.md` da API, "Mudanças no contrato").
Sem a opção marcada, o cadastro é o de sempre, com o teste de 7 dias e **sem** o campo.

| Resposta do cadastro | O que o app faz |
| --- | --- |
| `TESTE_JA_UTILIZADO` (sem chave) | Explica que este computador ou este telefone já usou o teste e que é preciso uma chave. **Marca a opção automaticamente**, mostra o campo e **foca nele**, e mostra o botão **"Assinar"** (fluxo do WhatsApp, voltando para esta tela; "Tenho uma chave" na tela de planos volta ao campo). Nenhuma conta foi criada; as senhas são limpas e precisam ser digitadas de novo. |
| `CHAVE_INVALIDA` | "Chave inválida: não existe, já foi utilizada ou foi cancelada. Nenhuma conta foi criada." A chave digitada é mantida para correção. |
| `MUITAS_TENTATIVAS` | Mostra o tempo de espera e **desabilita o botão durante o `Retry-After`** ("Aguarde N s"), mesmo com Enter. Sem o cabeçalho, espera 60 s. Vale também para a chave errada, que conta no limite por e-mail (10 em 15 minutos). |
| 201 | Login automático (como no teste) e `GET /licencas/status`. A barra de status mostra o **plano pago e a validade** (ou "Plano Vitalício"). |

## Limite de requisições (HTTP 429) no refresh, logout e status

`MUITAS_TENTATIVAS` em `POST /auth/refresh`, `POST /auth/logout` e
`GET /licencas/status` é uma **falha temporária**, nunca uma recusa:

- **A sessão não é encerrada.** O 429 do refresh não consome o refresh token, então o
  token salvo continua valendo e é reutilizado na próxima tentativa.
- **A janela principal não é bloqueada** e nada é perdido: não há aviso modal nem
  salvamento forçado. O app mostra um aviso discreto na barra de status
  ("Muitas tentativas ao validar a licença. Nova tentativa em N segundos. Sua sessão
  continua válida.").
- **O cache da licença não é apagado.**
- **Respeita o `Retry-After`**: a próxima tentativa só acontece depois dele (60 s se o
  cabeçalho faltar), **uma** por vez e no máximo **3 seguidas**; depois disso, só a
  validação de 1 hora. Não há laço de repetição. Qualquer sucesso zera a contagem.
- **Na abertura do app**, se houver cache dentro da carência de 72 horas, o app abre
  normalmente usando o cache (com o aviso de licença não validada) enquanto espera. Sem
  cache válido, mostra o login com o botão "Tentar novamente" desabilitado durante o
  `Retry-After`, e a sessão salva continua preservada.
- **Sair da conta** com 429: o app avisa na barra de status e continua conectado, sem
  oferecer "sair só neste computador" (isso é só para falha de rede).
- Uma licença já bloqueada continua bloqueada: o 429 nunca libera a janela.

## Assinatura pelo WhatsApp (fluxo manual)

Não há pagamento nem chamada à API nessa tela. O fluxo é:

1. O teste ou a licença vence (ou o usuário clica em **Assinar** no menu Conta ou
   na barra de status, que também aparece com 7 dias ou menos). Abre a tela
   **Assinar** com Mensal, Semestral, Anual e Vitalício (nome, duração, preço e
   botão **Escolher**). O Anual aparece destacado como "Mais vantajoso", sem
   desconto calculado.
2. Ao escolher, o app abre `https://wa.me/<whatsapp_numero>?text=<mensagem>`
   (texto codificado com `urllib.parse.quote`) com
   `QDesktopServices.openUrl`. Mensagem: `Olá! Quero assinar o DTF Manager.
   Plano: Anual (R$ 449,90). Nome: ... E-mail da conta: .... Telefone: ....`
   Nome, e-mail e telefone vêm da sessão (cadastro/login) ou do cache local da
   licença. O que não for conhecido é omitido; sem e-mail, a mensagem diz que o
   cliente vai informá-lo na conversa. **Nunca** vão senha, token nem ID da máquina.
3. A tela mostra: "Finalize o pagamento pelo WhatsApp. Quando receber a chave,
   clique em 'Tenho uma chave'.", com o botão **Tenho uma chave** (vai direto à
   tela de chave) e **Copiar mensagem** (caso o WhatsApp não abra).
4. Você conversa, recebe o pagamento, gera a chave no painel admin
   (`POST /admin/chaves` / página `/admin`) e envia ao cliente.
5. O cliente ativa em **Tenho uma chave** (e-mail, senha e chave) ou, com sessão,
   em **Conta → Renovar licença**. A chave é de uso único e a validade é somada à
   atual.

### Configuração embutida no executável (WhatsApp e suporte)

O número de WhatsApp e o contato de suporte **vêm embutidos no executável**, não do
ambiente do usuário final. Ficam em `dtf_manager/data/app_config.json`, incluído
no `build\dtf_manager.spec`:

```json
{ "whatsapp_numero": "5521999998888", "contato_suporte": "suporte@seudominio.com.br" }
```

- `whatsapp_numero`: formato internacional, **só dígitos**, de 10 a 15 dígitos.
- `contato_suporte`: texto livre (até 120 caracteres), mostrado nas mensagens que
  mandam falar com o suporte.
- Os arquivos aceitam UTF-8 com ou sem BOM (Bloco de Notas inclui o BOM).
- O repositório traz o valor de exemplo (`5511999999999`) e o contato vazio **de
  propósito**: o build falha até você preencher. Em tempo de execução o número de
  exemplo é tratado como "não configurado" (a tela avisa e não abre link).
- As variáveis `DTF_WHATSAPP_NUMBER` e `DTF_SUPPORT_CONTACT` continuam existindo,
  mas **só sobrescrevem, para desenvolvimento**. O gate de release ignora o
  ambiente e verifica o que realmente vai no pacote.

### Bloqueio do build

`.\build.ps1` roda `python app.py --release-check` **antes** do PyInstaller, e o
`--self-check` do executável congelado repete a verificação. O build falha, com
a mensagem `RELEASE BLOQUEADO: ...`, se:

| Condição | Mensagem |
| --- | --- |
| `whatsapp_numero` vazio | `whatsapp_numero está vazio em app_config.json.` |
| `whatsapp_numero` malformado (não são só dígitos, ou fora de 10 a 15) | `whatsapp_numero malformado em app_config.json: ...` |
| `whatsapp_numero` igual ao exemplo `5511999999999` | `whatsapp_numero ainda é o valor de exemplo ...` |
| `planos.json` com `"exemplo": true` | `planos.json ainda tem "exemplo": true ...` |
| `contato_suporte` vazio | `contato_suporte está vazio em app_config.json.` |
| arquivo ausente ou inválido | `app_config.json ausente ou inválido ...` / `planos.json ausente ou inválido.` |

Todas as falhas são listadas de uma vez. O `--self-check` também confirma, no
executável, que o número e o contato são lidos do arquivo empacotado **sem
nenhuma variável de ambiente**.

### Arquivo de planos

`dtf_manager/data/planos.json` (empacotado no executável). Cada plano tem
`codigo` (`MENSAL`, `SEMESTRAL`, `ANUAL` ou `VITALICIO`), `nome`, `duracao`,
`preco` e, opcionalmente, `destaque` (texto do selo). Os valores entregues são de
**EXEMPLO**, com `"exemplo": true`: enquanto isso, a tela mostra "(EXEMPLO)" ao lado
dos preços e um aviso. Troque os preços e mude `exemplo` para `false`. Para não
recompilar, aponte `DTF_PLANS_FILE` para um arquivo seu. Arquivo inválido gera
um aviso e a tela não abre. O preço do arquivo é o que vai na mensagem; o preço
real cobrado é combinado por você na conversa, e a duração do plano vem da chave.

## Variáveis de ambiente

| Variável | Padrão | Uso |
| --- | --- | --- |
| `DTF_API_URL` | `https://dtf-manager-api-production.up.railway.app` | URL da API. Exige `https://`; `http://` só para `localhost`, `127.0.0.1` ou `::1`. Valor inválido impede a abertura com uma mensagem. |
| `DTF_WHATSAPP_NUMBER` | `whatsapp_numero` de `app_config.json` | **Só sobrescrita para desenvolvimento.** Formato internacional, só dígitos. Valor inválido não cai no do pacote: a tela "Assinar" avisa e não abre link. |
| `DTF_PLANS_FILE` | `dtf_manager/data/planos.json` | Arquivo de planos e preços alternativo (permite trocar preços sem recompilar). |
| `DTF_PAYMENT_URL` | ausente | Opcional e secundário: página de compra no site, mostrada como "Ver planos no site". Só `https://`. |
| `DTF_ALLOW_NO_AUTH` | ausente | Precisa ser `1` para o modo `--no-auth`. |
| `DTF_SUPPORT_CONTACT` | `contato_suporte` de `app_config.json` | **Só sobrescrita para desenvolvimento.** Anexado às mensagens que mandam falar com o suporte. |
| `DTF_AUTH_TIMING` | ausente | `1` liga os tempos de diagnóstico (já existia). |

O alvo da credencial no Credential Manager não depende mais da URL:
`DTF Manager/session/production` para a API padrão e
`DTF Manager/session/dev-<hash>` para qualquer outra, de modo que um token de
desenvolvimento nunca é enviado à produção. A credencial antiga (com a URL no
nome) **não é migrada**: o usuário entra de novo uma vez.

## Desenvolvimento

API local (no projeto `dtf-manager-api`, com `DATABASE_URL` e secrets no `.env`):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Desktop apontando para ela:

```powershell
$env:DTF_API_URL = "http://127.0.0.1:8000"
python app.py
```

Desktop na produção (padrão): `Remove-Item Env:DTF_API_URL` e `python app.py`.

Sem autenticação e sem licença (somente código-fonte, nunca em build congelado):

```powershell
$env:DTF_ALLOW_NO_AUTH = "1"
python app.py --no-auth
```

Sem `DTF_ALLOW_NO_AUTH=1` o app recusa `--no-auth` e sai com código 2. O modo é
ignorado no executável empacotado, mesmo com a variável.

## Gerar o executável

```powershell
.\build.ps1                 # gera dist\DTFManager\DTFManager.exe e roda a verificação
.\build.ps1 -InstallDeps    # instala o requirements.txt antes
.\build.ps1 -Clean          # limpa a saída anterior
.\build.ps1 -RunTests       # roda os testes (um processo por módulo) antes
```

Antes de tudo ele confere a configuração embutida (veja "Bloqueio do build"). O script usa `build\dtf_manager.spec` (versionado), gera uma pasta
(`one-folder`) e **não cria instalador**. Em seguida executa
`DTFManager.exe --self-check <arquivo>`, que roda no executável congelado, sem
janela nem rede, e confirma que SMBIOS por `ctypes`, a leitura do disco, o DPAPI e
o Credential Manager funcionam. O relatório não contém seriais nem o ID.

## Testes

Cada módulo precisa rodar em um processo próprio (várias janelas Qt no mesmo
processo derrubam o interpretador ao sair, comportamento já existente):

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
Get-ChildItem tests -Filter test_*.py | ForEach-Object { python -m unittest "tests.$($_.BaseName)" }
```

Os testes usam clientes, credenciais, cache e relógio simulados: não acessam a
rede, o Credential Manager nem o cache real. Apenas `test_machine_id`,
`test_offline_grace` (DPAPI em pasta temporária) e `test_self_check` tocam o
hardware e o DPAPI do computador em que rodam.
