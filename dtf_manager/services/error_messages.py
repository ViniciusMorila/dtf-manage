"""User-facing texts (pt-BR) by API error code, with fallback to error.message."""
from dtf_manager.core import config

_MESSAGES = {
    "INVALID_CREDENTIALS": "E-mail ou senha inválidos.",
    "INVALID_ACCESS_TOKEN": "Sua sessão expirou. Entre novamente.",
    "INVALID_REFRESH_TOKEN": (
        "Sua sessão foi encerrada. Isso acontece quando a conta entra em outro computador "
        "(só uma sessão fica ativa por vez) ou quando a licença é bloqueada ou redefinida. "
        "Entre novamente."),
    "LICENCA_EXPIRADA": "Sua licença expirou. Ative uma nova chave para continuar.",
    "LICENCA_BLOQUEADA": "Sua licença foi bloqueada. Entre em contato com o suporte.",
    "LICENCA_NAO_ENCONTRADA": "Esta conta não possui licença. Ative uma chave para continuar.",
    "LICENCA_JA_VITALICIA": "Sua licença já é vitalícia. A chave não foi consumida.",
    "LICENCA_INDISPONIVEL": "A validação da licença está temporariamente indisponível. Tente novamente em instantes.",
    "MAQUINA_DIFERENTE": (
        "Esta licença está vinculada a outro computador. Para usá-la neste, peça ao suporte "
        "a troca de computador (reset da máquina)."),
    "MAQUINA_EM_USO": "Este computador já possui uma licença ativa em outra conta.",
    "ID_MAQUINA_INVALIDO": "Não foi possível identificar este computador. Entre em contato com o suporte.",
    "TESTE_JA_UTILIZADO": (
        "O período de teste já foi utilizado neste computador ou com este telefone. "
        "Entre em contato com o suporte para adquirir uma licença."),
    "CHAVE_INVALIDA": "Chave de ativação inválida, já utilizada ou cancelada. Confira o código digitado.",
    "LIMITE_RESETS": "O limite de trocas de computador desta licença foi atingido. Entre em contato com o suporte.",
    "TELEFONE_INVALIDO": "Telefone inválido. Informe um telefone brasileiro com DDD.",
    "EMAIL_ALREADY_EXISTS": "Já existe uma conta com este e-mail.",
    "WEAK_PASSWORD": "Senha fraca. Use no mínimo 8 caracteres, com letras e números.",
    "VALIDATION_ERROR": "Alguns dados são inválidos. Confira os campos e tente novamente.",
    "REGISTRATION_UNAVAILABLE": "O cadastro está indisponível no momento. Tente novamente em instantes.",
    "REGISTRATION_FAILED": "Não foi possível concluir o cadastro. Tente novamente.",
    "AUTHENTICATION_UNAVAILABLE": "A autenticação está indisponível no momento. Tente novamente em instantes.",
    "AUTHENTICATION_FAILED": "Não foi possível autenticar agora. Tente novamente.",
    "ACESSO_NEGADO": "Acesso negado.",
}
_KINDS = {
    "network": "Não foi possível conectar ao servidor. Verifique sua conexão e tente novamente.",
    "timeout": "O servidor demorou para responder. Tente novamente.",
    "invalid_json": "Não foi possível validar a resposta do servidor. Tente novamente.",
    "server": "O serviço está indisponível no momento. Tente novamente.",
    "unauthorized": "Sua sessão é inválida. Entre novamente.",
}
SUPPORT_CODES = {"MAQUINA_DIFERENTE", "LICENCA_BLOQUEADA", "LIMITE_RESETS", "ID_MAQUINA_INVALIDO"}


def format_wait(seconds):
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds} segundo" + ("" if seconds == 1 else "s")
    minutes = -(-seconds // 60)
    if minutes < 60:
        return f"{minutes} minuto" + ("" if minutes == 1 else "s")
    hours = -(-minutes // 60)
    return f"{hours} hora" + ("" if hours == 1 else "s")


def describe(failure):
    """Text for an ApiFailure. Server text is only a fallback and is sanitized upstream."""
    if failure.kind == "rate_limited" or failure.code == "MUITAS_TENTATIVAS":
        text = "Muitas tentativas."
        if failure.retry_after:
            return f"{text} Aguarde {format_wait(failure.retry_after)} para tentar novamente."
        return f"{text} Aguarde alguns instantes para tentar novamente."
    text = _MESSAGES.get(failure.code)
    if text is None and failure.code is None:
        text = _KINDS.get(failure.kind)
    if text is None:
        text = failure.message or _KINDS.get(failure.kind) or _KINDS["server"]
    if failure.code in SUPPORT_CODES:
        contact = config.support_contact()
        if contact:
            text += f"\nSuporte: {contact}"
    return text
