"""Form validation helpers (the server validates again; these only help the user)."""
import re

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def phone_digits(text):
    """Digits of a Brazilian phone without the +55 country code."""
    text = (text or "").strip()
    digits = re.sub(r"\D", "", text)
    if (text.startswith("+") and digits.startswith("55")) or (
            digits.startswith("55") and len(digits) in {12, 13}):
        digits = digits[2:]
    return digits


def normalize_phone(text):
    """Digits-only phone when it is a valid Brazilian number with area code, else None.

    Mobile: DDD + 9 + 8 digits. Landline: DDD + 8 digits starting with 2 to 5.
    """
    digits = phone_digits(text)
    if len(digits) not in {10, 11} or not "11" <= digits[:2] <= "99" or digits[0] == "0":
        return None
    if len(digits) == 11:
        return digits if digits[2] == "9" else None
    return digits if digits[2] in "2345" else None


def format_phone_mask(text):
    """Progressive mask: (11) 91234-5678 or (11) 3123-4567."""
    digits = phone_digits(text)[:11]
    if not digits:
        return ""
    if len(digits) <= 2:
        return "(" + digits
    if len(digits) <= 6:
        return f"({digits[:2]}) {digits[2:]}"
    if len(digits) <= 10:
        return f"({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return f"({digits[:2]}) {digits[2:7]}-{digits[7:]}"


def validate_name(text):
    value = (text or "").strip()
    if not value:
        return "Informe seu nome."
    if len(value) > 200:
        return "O nome pode ter no máximo 200 caracteres."
    return None


def validate_email(text):
    value = (text or "").strip()
    if not value:
        return "Informe seu e-mail."
    if len(value) > 254 or not _EMAIL.match(value):
        return "Informe um e-mail válido."
    return None


def validate_password(text):
    value = text or ""
    if len(value) < 8 or not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        return "A senha precisa ter no mínimo 8 caracteres, com ao menos uma letra e um número."
    return None
