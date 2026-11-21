"""Redacção de padrões sensíveis em texto que pode ir para logs ou registos.

Defesa em profundidade: o gateway não guarda conteúdo de mensagens, mas mensagens de erro
de providers ou valores livres (ex.: nomes de equipa) podem conter dados pessoais. Esta
camada remove emails, telefones, números de cartão e chaves virtuais/de provider antes
de qualquer escrita.
"""

from __future__ import annotations

import logging
import re
from typing import Any

REDACTED = "[REDACTED]"

_PHONE = re.compile(r"(?<![\w.])\+?\d[\d ().\-]{7,}\d(?![\w.])")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"mm_live_[A-Za-z0-9]{32}"), REDACTED),
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), REDACTED),
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), REDACTED),
)


def _digits_at_least(match: re.Match[str], minimum: int) -> str:
    digits = sum(ch.isdigit() for ch in match.group(0))
    return REDACTED if digits >= minimum else match.group(0)


def redact(text: str) -> str:
    """Substitui padrões sensíveis. Nunca levanta excepção: entrada não-string devolve ''.

    Telefones e cartões só são redactados com um número mínimo de dígitos, para não
    apagar datas curtas (ex.: 2026-11-20) de mensagens de log.
    """
    if not isinstance(text, str):
        return ""
    result = text
    for pattern, replacement in _PATTERNS:
        result = pattern.sub(replacement, result)
    result = _CARD.sub(lambda m: _digits_at_least(m, 13), result)
    result = _PHONE.sub(lambda m: _digits_at_least(m, 9), result)
    return result


def redact_value(value: Any) -> Any:
    """Redacta recursivamente strings dentro de estruturas simples (dict/list/tuple)."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v) for v in value]
    return value


class RedactingFilter(logging.Filter):
    """Filtro de logging: redacta a mensagem final e os argumentos de string."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = None
        return True
