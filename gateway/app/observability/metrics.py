"""Métricas Prometheus com registo próprio por aplicação (sem estado global).

Nomes com prefixo `modelmesh_`. Etiquetas com cardinalidade controlada: equipa, modelo,
provider e motivo. Nunca `request_id`, `trace_id` ou identificadores de chave completos.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest

LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

# Motivos de erro válidos (conjunto fechado, para controlar cardinalidade).
ERROR_REASONS = frozenset(
    {
        "invalid_api_key",
        "forbidden",
        "model_not_allowed",
        "invalid_request",
        "max_tokens_exceeded",
        "body_too_large",
        "validation_error",
        "rate_limited",
        "budget_exceeded",
        "upstream_unavailable",
        "upstream_client_error",
        "timeout",
        "pricing_missing",
        "service_unavailable",
        "internal_error",
    }
)


class GatewayMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry(auto_describe=True)
        self.requests = Counter(
            "modelmesh_request",
            "Pedidos de inferência recebidos e terminados",
            ["team", "model", "status"],
            registry=self.registry,
        )
        self.errors_by_reason = Counter(
            "modelmesh_errors_by_reason",
            "Erros devolvidos ao cliente por motivo",
            ["team", "reason"],
            registry=self.registry,
        )
        self.fallback = Counter(
            "modelmesh_fallback",
            "Pedidos servidos por fallback (from -> to)",
            ["team", "from", "to"],
            registry=self.registry,
        )
        self.rate_limit_rejections = Counter(
            "modelmesh_rate_limit_rejections",
            "Pedidos rejeitados por rate limit",
            ["team", "scope", "kind"],
            registry=self.registry,
        )
        self.budget_rejections = Counter(
            "modelmesh_budget_rejections",
            "Pedidos rejeitados por orçamento",
            ["team", "scope"],
            registry=self.registry,
        )
        self.token_usage = Counter(
            "modelmesh_token_usage",
            "Tokens consumidos por provider e modelo",
            ["team", "provider", "model", "direction"],
            registry=self.registry,
        )
        self.estimated_spend = Counter(
            "modelmesh_estimated_spend_usd",
            "Custo real reconciliado em USD",
            ["team", "provider", "model"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "modelmesh_latency_seconds",
            "Latência end-to-end do gateway",
            ["team", "model"],
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.provider_attempts = Counter(
            "modelmesh_provider_attempts",
            "Tentativas por provider e resultado",
            ["provider", "outcome"],
            registry=self.registry,
        )

    def render(self) -> bytes:
        return generate_latest(self.registry)


def reason_label(reason: str) -> str:
    return reason if reason in ERROR_REASONS else "internal_error"
