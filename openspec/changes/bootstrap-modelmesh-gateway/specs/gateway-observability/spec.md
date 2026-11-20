# Spec Delta

## Purpose

Dar à equipa de plataforma visibilidade sobre tráfego, erros, custos e latência do gateway, e um painel para gerir equipas, chaves e políticas.

## ADDED Requirements

### Requirement: Métricas
`GET /metrics` SHALL expor em formato Prometheus `request_total`, `errors_by_reason`, `fallback_total`, `rate_limit_rejections`, `budget_rejections`, `token_usage`, `estimated_spend` e `latency_histogram`, etiquetadas por equipa, modelo e provider, sem etiquetas de alta cardinalidade como `request_id`. O acesso MUST ser protegido conforme o deployment.

#### Scenario: Fallback contado
- **WHEN** ocorrem 3 pedidos com fallback A→B
- **THEN** `fallback_total{from="A",to="B"}` aumenta 3

### Requirement: Tracing distribuído
Cada pedido SHALL criar um trace OpenTelemetry com spans por etapa (auth, policy, rate limit, budget, cada hop, reconciliação) e MUST propagar o `traceparent` recebido.

#### Scenario: Traceparent do cliente
- **WHEN** o cliente envia `traceparent`
- **THEN** os spans do gateway pertencem ao mesmo trace

### Requirement: Health checks
`GET /health/live` SHALL indicar que o processo está vivo. `GET /health/ready` MUST indicar se Redis e Postgres estão acessíveis e se há pelo menos um provider com circuito fechado.

#### Scenario: Redis em baixo
- **WHEN** o Redis não responde
- **THEN** `/health/ready` devolve `503` e o pedido de inferência é rejeitado (fail-closed) em vez de ignorar limites

### Requirement: Painel de administração
O painel SHALL permitir gerir equipas, chaves (mostrada uma vez), orçamentos e políticas, e mostrar consumo, distribuição de modelos, latência p50/p95, erros por provider, o estado dos circuitos e um testador de failover. `GET /admin/routes` SHALL devolver a resolução de rotas efectiva por equipa.

#### Scenario: Testador de failover
- **WHEN** um admin força falhas no mock A pelo painel
- **THEN** o painel mostra os pedidos de teste a passar para B e o circuito de A a abrir
