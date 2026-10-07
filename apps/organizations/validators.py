import re

from django.core.exceptions import ValidationError

_CNPJ_PATTERN = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_DISPLAY_CHARACTERS = str.maketrans("", "", "./-")


def normalize_tax_identifier(value: str) -> str:
    """Return the canonical 14-character CNPJ representation.

    Since July 2026 the first 12 positions may be digits or uppercase letters;
    the final two positions remain numeric check digits.
    """
    return value.strip().upper().translate(_DISPLAY_CHARACTERS)


def _check_digit(characters: str, weights: tuple[int, ...]) -> int:
    total = sum((ord(character) - 48) * weight for character, weight in zip(characters, weights, strict=True))
    remainder = total % 11
    return 0 if remainder < 2 else 11 - remainder


def validate_tax_identifier(value: str) -> None:
    """Validate numeric and alphanumeric CNPJ values using Receita's modulus 11."""
    canonical = normalize_tax_identifier(value)
    if not _CNPJ_PATTERN.fullmatch(canonical):
        raise ValidationError("Informe um CNPJ válido com 14 posições.")

    first_digit = _check_digit(canonical[:12], (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    second_digit = _check_digit(canonical[:12] + str(first_digit), (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    if canonical[-2:] != f"{first_digit}{second_digit}":
        raise ValidationError("Informe um CNPJ com dígitos verificadores válidos.")

