"""Tracing OpenTelemetry com propagação W3C `traceparent`.

Cada aplicação tem o seu `TracerProvider` (sem estado global), o que permite testes isolados.
Se `otlp_endpoint` estiver definido, exporta por OTLP/HTTP; caso contrário, os spans ficam
num exportador em memória (útil para testes) ou não são exportados.
"""

from __future__ import annotations

from collections.abc import Mapping

from opentelemetry import context as otel_context
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor, SpanExporter
from opentelemetry.trace import Tracer
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_propagator = TraceContextTextMapPropagator()


def build_tracer_provider(
    *,
    service_name: str = "modelmesh-gateway",
    exporter: SpanExporter | None = None,
    otlp_endpoint: str | None = None,
) -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    return provider


def get_tracer(provider: TracerProvider) -> Tracer:
    return provider.get_tracer("modelmesh.gateway")


def extract_parent_context(headers: Mapping[str, str]) -> otel_context.Context:
    """Lê `traceparent` (e `tracestate`) do pedido do cliente. Sem cabeçalho -> contexto vazio."""
    carrier = {
        k.lower(): v for k, v in headers.items() if k.lower() in ("traceparent", "tracestate")
    }
    return _propagator.extract(carrier=carrier)


def trace_id_hex(span) -> str | None:  # noqa: ANN001 - Span do OpenTelemetry
    context = span.get_span_context()
    if not context or not context.is_valid:
        return None
    return format(context.trace_id, "032x")
