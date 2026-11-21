"""Chaves virtuais: geração, hash e prefixo.

Formato: `mm_live_` + 32 caracteres base62 aleatórios (~190 bits de entropia).
Guarda-se apenas `sha256(chave)` e um prefixo identificável. Para segredos aleatórios de
alta entropia, um hash rápido basta: bcrypt/argon2 servem para palavras-passe humanas, que
têm entropia baixa e precisam de custo computacional contra adivinhação.
"""

from __future__ import annotations

import hashlib
import re
import secrets
import string
from dataclasses import dataclass

KEY_PREFIX_LITERAL = "mm_live_"
_BASE62 = string.ascii_letters + string.digits
_RANDOM_LEN = 32
# O prefixo mostrado na administração inclui o literal e os primeiros 8 caracteres aleatórios.
IDENT_PREFIX_LEN = len(KEY_PREFIX_LITERAL) + 8
_KEY_RE = re.compile(r"^mm_live_[A-Za-z0-9]{32}$")


@dataclass(frozen=True)
class IssuedKey:
    plaintext: str  # mostrada UMA vez
    key_hash: str
    prefix: str


def generate_key() -> IssuedKey:
    random_part = "".join(secrets.choice(_BASE62) for _ in range(_RANDOM_LEN))
    plaintext = KEY_PREFIX_LITERAL + random_part
    return IssuedKey(
        plaintext=plaintext,
        key_hash=hash_key(plaintext),
        prefix=plaintext[:IDENT_PREFIX_LEN],
    )


def hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def looks_like_virtual_key(value: object) -> bool:
    """Verificação de formato, sem consultar a base de dados."""
    return isinstance(value, str) and _KEY_RE.match(value) is not None
