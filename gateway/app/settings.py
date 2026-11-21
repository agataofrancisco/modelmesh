"""Configuração do gateway, lida de variáveis de ambiente com prefixo MODELMESH_.

Segredos NUNCA entram aqui como valor literal de config versionada: o `admin_token`
vem do ambiente e as chaves dos providers são referenciadas por nome de variável
(`api_key_env`), nunca por valor.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderConfig(BaseModel):
    """Um provider compatível com OpenAI. `api_key_env` aponta para a variável de ambiente."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=8, max_length=300)
    api_key_env: str | None = Field(default=None, max_length=100)
    control_url: str | None = Field(default=None, max_length=300)

    @field_validator("base_url")
    @classmethod
    def _http_only(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("base_url deve começar por http:// ou https://")
        return value.rstrip("/")


DEFAULT_PROVIDERS: dict[str, ProviderConfig] = {
    "mock_a": ProviderConfig(
        base_url="http://127.0.0.1:9001/v1", control_url="http://127.0.0.1:9001"
    ),
    "mock_b": ProviderConfig(
        base_url="http://127.0.0.1:9002/v1", control_url="http://127.0.0.1:9002"
    ),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODELMESH_", extra="ignore")

    env: str = "dev"
    database_url: str = "sqlite+aiosqlite:///./.runtime/modelmesh.db"
    redis_url: str = "redis://127.0.0.1:6379/0"
    admin_token: SecretStr | None = None
    providers: dict[str, ProviderConfig] = Field(default_factory=lambda: dict(DEFAULT_PROVIDERS))

    # Fail-closed: sem Redis não há limites nem orçamento verificável, por isso recusa-se.
    fail_closed: bool = True
    max_body_bytes: int = Field(default=256_000, ge=1_024, le=5_000_000)
    max_messages: int = Field(default=200, ge=1, le=2_000)

    # Reservas e sweeper de órfãs.
    reservation_ttl_s: int = Field(default=120, ge=5, le=3_600)
    sweeper_interval_s: float = Field(default=5.0, gt=0)
    concurrency_safety_ttl_s: int = Field(default=300, ge=10, le=3_600)

    # Circuit breaker: abre quando há >= min_requests na janela e a taxa de falhas >= ratio.
    circuit_window_s: float = Field(default=30.0, gt=0)
    circuit_min_requests: int = Field(default=5, ge=1)
    circuit_failure_ratio: float = Field(default=0.5, gt=0, le=1)
    circuit_cooldown_s: float = Field(default=10.0, gt=0)

    # Retries: min(cap, base * 2^n) * jitter.
    retry_base_s: float = Field(default=0.2, ge=0)
    retry_cap_s: float = Field(default=2.0, ge=0)

    otel_exporter_otlp_endpoint: str | None = None
    log_level: str = "INFO"
    prices_seed_path: str = "migrations/seed/prices.yaml"

    @property
    def admin_token_value(self) -> str | None:
        return self.admin_token.get_secret_value() if self.admin_token else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
