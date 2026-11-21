# Instalador (Inno Setup)

## Versão
Fonte única: `dtf_manager/core/version.py` (`APP_VERSION = "x.y.z"`). O `build.ps1` lê esse arquivo e passa
`/DAppVersion=x.y.z` ao `installer.iss`. A versão aparece na barra de título da janela principal.

## Gerar o Setup
1. Instale o Inno Setup 6 (https://jrsoftware.org/isdl.php) no caminho padrão
   (`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`, ou `C:\Program Files\Inno Setup 6\`, ou
   `%LOCALAPPDATA%\Programs\Inno Setup 6\`, ou ISCC.exe no PATH). Sem ele o `build.ps1` falha com essa mensagem.
2. Preencha `dtf_manager\data\app_config.json` e `planos.json` com valores reais (o release gate exige).
3. Rode `.\build.ps1 -Clean -RunTests`. Ordem: testes, release gate, checagem do ISCC, PyInstaller, self-check do
   executável, instalador, SHA-256.
4. Saída em `installer_output\`: `DTFManager-Setup-<versão>.exe` e `DTFManager-Setup-<versão>.sha256`.

## Regras do instalador
- Instalação por usuário (sem administrador): `%LOCALAPPDATA%\Programs\DTF Manager`.
- `AppId` fixo `{C4111349-E156-43E9-BD99-978D3DB85F41}`: nunca mude (é o que faz a atualização reconhecer a instalação).
- `AppMutex=DTFManager-AppMutex`: o app cria esse mutex ao abrir (`core/app_mutex.py`). O instalador fecha o app
  aberto e tenta reiniciá-lo (`CloseApplications`/`RestartApplications`).
- Reabertura: caixa "Abrir DTF Manager" no fim da instalação normal; em instalação silenciosa (`/SILENT`,
  `/VERYSILENT`) o app abre sozinho. É isso que permite a atualização automática reiniciar o app.
- Dados do usuário NÃO ficam na pasta de instalação e não são apagados ao desinstalar ou atualizar:
  - `%LOCALAPPDATA%\DTF Manager\DTF Manager` (banco `dtf_manager.db`, cache da licença, histórico, memória de vínculos,
    operação em andamento, cópias de segurança);
  - registro `HKCU\Software\DTF Manager` (configurações, pasta das artes);
  - Gerenciador de Credenciais do Windows (sessão).
  Não há seção `[UninstallDelete]` de propósito.

## Testar numa VM limpa
1. Copie o `.exe` e o `.sha256` para a VM e confira: `Get-FileHash .\DTFManager-Setup-1.0.0.exe -Algorithm SHA256`
   (deve ser igual ao do `.sha256`).
2. Execute o Setup (o SmartScreen avisa porque não é assinado: "Mais informações" > "Executar assim mesmo").
   Marque o atalho na área de trabalho. Confira o menu Iniciar, a abertura final e o login.
3. Com o app aberto, instale uma versão nova (suba `APP_VERSION`, gere de novo) rodando
   `DTFManager-Setup-1.0.1.exe /VERYSILENT`: o app fecha, atualiza e reabre sozinho; banco e licença continuam.
4. Desinstale em Configurações > Aplicativos: a pasta de dados em `%LOCALAPPDATA%\DTF Manager` permanece.
