# Proposal

## Why

Quando várias equipas de uma empresa começam a usar LLMs, cada uma cria as suas chaves, escolhe modelos ao acaso e ninguém sabe quanto se gasta. Quando um provider falha, as aplicações também falham. O ModelMesh é um gateway compatível com a API da OpenAI que centraliza autenticação por equipa, política de routing, quotas, orçamentos, failover e observabilidade. O diferencial não é reimplementar o LiteLLM. É um **policy engine próprio**, **orçamentos atómicos sob concorrência** e **testes de chaos** que provam o comportamento quando os providers falham.

Domínio fictício: a equipa de plataforma da **Órbita Tech** (tenant `orbita`), que serve as equipas `suporte`, `marketing` e `dados`. Os providers reais são opcionais. Os providers mock simulam falhas.

## What Changes

- Projecto novo `projects/modelmesh`: FastAPI, Redis, Postgres, Prometheus/OpenTelemetry/Grafana e painel React.
- `POST /v1/chat/completions` compatível com OpenAI (não-streaming nesta change), autenticado com chaves virtuais guardadas como hash.
- Policy engine: modelos permitidos por equipa, classes de tarefa `cheap`/`balanced`/`critical`, cadeias de fallback limitadas, circuit breaker com cooldown, retries só para erros transitórios com backoff + jitter, e timeout por hop.
- Rate limit atómico (RPM, TPM estimado, concorrência) e orçamentos por equipa e por chave, com reserva antes do pedido e reconciliação depois.
- Contabilidade de custos com tabela de preços versionada (`effective_date`, moeda e fonte).
- Métricas, tracing e uma API de administração separada da inferência.
- Providers mock A/B com timeout, 429, 5xx, latência, JSON inválido e falta de `usage`. Script de chaos e benchmark de overhead.
- Documentação de aprendizagem em `docs/learn/`.

## Capabilities

### New Capabilities
- `inference-api`: endpoint compatível com OpenAI, validação de pedidos e formato de erros.
- `virtual-keys`: emissão, hash, revogação e escopo de chaves por equipa, separadas de credenciais de admin.
- `routing-policy`: selecção de modelo por política, fallback, circuit breaker, retries e timeouts.
- `rate-limits-and-budgets`: limites RPM/TPM/concorrência e orçamentos com reserva e reconciliação atómicas.
- `usage-accounting`: tokens, custos com preços versionados e registo de uso com redacção.
- `gateway-observability`: métricas, tracing, health checks e painel de administração.
- `resilience-testing`: providers simulados, cenários de chaos e benchmark de overhead.

### Modified Capabilities
<!-- Nenhuma: projecto novo. -->

## Impact

- **Código novo**: `gateway/` (FastAPI), `frontend/`, `migrations/`, `chaos/`, `bench/`, `deploy/` (Prometheus/Grafana) e `docs/`.
- **Dependências** (confirmar versões): FastAPI, Pydantic v2, httpx, redis-py, SQLAlchemy/Alembic, prometheus-client, OpenTelemetry SDK. LiteLLM é opcional, apenas para normalizar providers, e com a fronteira documentada.
- **Infraestrutura**: Redis e Postgres. Sem Docker local, os testes de atomicidade usam um Redis real quando disponível (`-m redis`). O fakeredis só serve para testes unitários e não prova a atomicidade.
- **Fora de âmbito**: streaming SSE (fase 2), embeddings, SSO e routing por custo/qualidade (é a change `add-cost-autopilot`).
