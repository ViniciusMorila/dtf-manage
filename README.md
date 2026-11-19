# DTF Manager

Base desktop nativa para montagem de rolos de artes para impressao DTF.

## Requisitos

- Python 3.12+
- Windows

## Executar

```powershell
python -m pip install -r requirements.txt
python app.py
```

Por padrão, o aplicativo não usa recarregamento automático. Durante o
desenvolvimento, ele pode ser ativado explicitamente com `python app.py --reload`.

Para abrir a interface localmente sem autenticação ou validação de licença,
defina `DTF_ALLOW_NO_AUTH=1` e execute `python app.py --no-auth`. Sem a variável
o app recusa o modo. Ele é exclusivo da execução do código-fonte (não funciona em
builds empacotados), é marcado no título da janela e não deve ser usado para produção.

## Licenças, API e executável

- `DTF_API_URL`: URL da API (padrão: produção). Ex.: `http://127.0.0.1:8000`.
- `DTF_PAYMENT_URL`: página de compra aberta pelo botão "Ver planos e comprar".
- `.uild.ps1`: gera `dist\DTFManager\DTFManager.exe` (sem instalador).

Detalhes, carência offline de 72 horas e ID da máquina em
[docs/licencas_desktop.md](docs/licencas_desktop.md).

A primeira entrega concentra-se na interface. A cena do rolo ja esta isolada para receber posicionamento em milimetros, e a exportacao possui um ponto de extensao separado da UI.
