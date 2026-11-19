"""Release gate: the packaged configuration must be real before an executable ships.

Reads the files bundled in the application (never the environment overrides),
so it checks exactly what the end user would get.
"""
import json

from dtf_manager.core import config
from dtf_manager.services import plans


def _load(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def release_problems(app_config_file=None, plans_file=None):
    """Messages (pt-BR) for everything that blocks a release; empty means ready."""
    problems = []
    app_file = app_config_file or config.APP_CONFIG_FILE
    data = _load(app_file)
    if data is None:
        problems.append(f"app_config.json ausente ou inválido ({app_file.name}).")
        data = {}
    number = config.text_field(data, "whatsapp_numero")
    if not number:
        problems.append("whatsapp_numero está vazio em app_config.json.")
    elif not config.valid_whatsapp(number):
        problems.append("whatsapp_numero malformado em app_config.json: use só dígitos, "
                        "formato internacional (ex.: 5511999999999), de 10 a 15 dígitos.")
    elif number == config.EXAMPLE_WHATSAPP:
        problems.append("whatsapp_numero ainda é o valor de exemplo (5511999999999). Informe o número real.")
    if not config.text_field(data, "contato_suporte"):
        problems.append("contato_suporte está vazio em app_config.json.")
    plans_data = _load(plans_file or plans.DEFAULT_PLANS_FILE)
    if plans_data is None:
        problems.append("planos.json ausente ou inválido.")
    elif plans_data.get("exemplo") is True:
        problems.append('planos.json ainda tem "exemplo": true. Troque os preços e use "exemplo": false.')
    return problems
