# 09 · Observabilidade: métricas, tracing e health checks

## O problema

Quando um fallback acontece às 3 da manhã, a equipa precisa de saber: que par falhou, quantas vezes,
quanto custou e onde o tempo foi gasto. Sem isto, cada incidente é uma investigação.

## O que entra e o que sai

Entra cada pedido e cada tentativa. Saem:

- `GET /metrics` (formato Prometheus), com nomes prefixados por `modelmesh_`.
- Spans OpenTelemetry por etapa, com o `traceparent` do cliente como pai.
- `GET /health/live` e `GET /health/ready`.

Métricas expostas (verificadas contra a saída real de `GatewayMetrics.render()`):

| Métrica | Etiquetas | Uso |
|---|---|---|
| `modelmesh_request_total` | team, model, status | tráfego e erros |
| `modelmesh_errors_by_reason_total` | team, reason | motivos (conjunto fechado) |
| `modelmesh_fallback_total` | team, from, to | pares de fallback |
| `modelmesh_rate_limit_rejections_total` | team, scope, kind | limites atingidos |
| `modelmesh_budget_rejections_total` | team, scope | orçamento esgotado |
| `modelmesh_token_usage_total` | team, provider, model, direction | tokens |
| `modelmesh_estimated_spend_usd_total` | team, provider, model | custo reconciliado |
| `modelmesh_latency_seconds` (histograma) | team, model | p50/p95 |
| `modelmesh_provider_attempts_total` | provider, outcome | tentativas |

Os nomes foram confirmados na saída real: `modelmesh_fallback_total{from="mock_a",team="suporte",to="mock_b"} 1.0`.

## Como funciona por dentro

- `gateway/app/observability/metrics.py`: um `CollectorRegistry` **por aplicação**, sem estado
  global. Os testes criam várias aplicações sem colisões.
- Cardinalidade controlada: nunca `request_id`, `trace_id` ou identificadores completos de chave.
  O teste `test_fallback_counted_and_traceparent_shared` verifica que `request_id` não aparece no
  `/metrics`.
- `gateway/app/observability/tracing.py`: propaga `traceparent` com `TraceContextTextMapPropagator`.
  O pipeline cria o span raiz como filho do contexto recebido
  (`gateway/app/pipeline.py:handle`, `start_as_current_span(..., context=parent_ctx)`).
  O teste confirma que `x-modelmesh-trace-id` é igual ao trace-id enviado pelo cliente.
- `health.py:ready` verifica Redis (PING), Postgres (`SELECT 1`) e se há pelo menos um hop com
  circuito fechado. Sem Redis devolve `503`.

Saída real de um pedido com `traceparent` (teste): `x-modelmesh-trace-id: 4bf92f3577b34da6a3ce929d0e0e4736`.

## Porquê esta escolha

- **Prometheus para métricas agregadas, OTel para o caminho de um pedido**: métricas são baratas e
  agregáveis; traces mostram a sequência de um pedido concreto.
- **Registo próprio**: evita duplicação de métricas quando há várias apps no mesmo processo.
- **`/metrics` na rede privada**: contém nomes de equipas e modelos. Não deve ser público. Está
  configurado sem `ports` públicos no `docker-compose.yml`.

## Alternativas

- Só logs estruturados: difíceis de agregar e caros em volume.
- Métricas com `request_id`: explodem a cardinalidade e tornam o Prometheus inutilizável.

## Como falha

- Fallback contado: `test_fallback_counted_and_traceparent_shared`.
- Ready com Redis em baixo: `test_redis_down_fails_closed_with_503` (`/health/ready` = 503).
- Evento de órfã registado: `test_orphan_event_logged`.

**Não testado localmente**: o stack Prometheus e Grafana (`deploy/`). Sem Docker, o JSON do
dashboard e o `prometheus.yml` foram validados apenas em sintaxe e nos nomes de métricas acima.

## Perguntas de entrevista

1. **Porque é que `request_id` não pode ser etiqueta?** Cada valor cria uma série nova no
   Prometheus. Com milhões de pedidos, a memória do servidor rebenta.
2. **Qual a diferença entre um trace e uma métrica?** Uma métrica agrega; um trace conta a história
   de um pedido. Usam-se as duas para perguntas diferentes.
3. **Como se calcula p95 a partir de um histograma?** Com `histogram_quantile` sobre os buckets
   cumulativos. Dá uma estimativa limitada pelos limites dos buckets.
