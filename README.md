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
execute `python app.py --no-auth`. Esse modo é exclusivo da execução do código-fonte
(não funciona em builds empacotados), é marcado no título da janela e não deve ser
usado para produção.

A primeira entrega concentra-se na interface. A cena do rolo ja esta isolada para receber posicionamento em milimetros, e a exportacao possui um ponto de extensao separado da UI.
