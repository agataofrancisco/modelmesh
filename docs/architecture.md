# Arquitetura

## Componentes

```text
cliente (SDK OpenAI)
    |  Bearer mm_live_...
    v
gateway (FastAPI, uvicorn)  ---- Redis: rate limit, orçamento, circuitos (Lua)
    |                       ---- Postgres: equipas, chaves, políticas, preços, registo de uso
    |  httpx (timeouts por hop)
    v
provider A / provider B  (OpenAI-compatible: OpenRouter/OpenAI ou mock_provider_a/b)
```

- `gateway/app/api`: rotas de inferência, administração, health e métricas.
- `gateway/app/auth`: chaves virtuais (hash) e credencial de administração.
- `gateway/app/policy`: política, resolução de rotas, executor de fallback, backoff, circuit breaker.
- `gateway/app/limits`: rate limit atómico (Lua).
- `gateway/app/budget`: reserva, reconciliação e sweeper (Lua).
- `gateway/app/accounting`: preços versionados, custo, redacção.
- `gateway/app/providers`: adaptador `openai_compatible`, taxonomia de erros, mock provider.
- `gateway/app/observability`: métricas Prometheus e tracing OTel.
- `gateway/app/store`: modelos SQLAlchemy, repositório, seed.
- `migrations/`: Alembic (migração `0001_initial_schema`) e seed demo.
- `frontend/`: painel React (Vite). Consome a API de administração com um token.
- `chaos/`, `bench/`: cenários de chaos e benchmark de overhead.
- `deploy/`: Prometheus e dashboard Grafana (não testados localmente).

## Dados

| Tabela | Conteúdo | Notas |
|---|---|---|
| `teams` | id, nome | |
| `api_keys` | prefixo, hash SHA-256, estado, limites e orçamento opcionais | nunca a chave em claro |
| `policies` | versão, corpo JSON validado | histórico por versão |
| `prices` | preço por (provider, modelo, data de vigência) | fonte e moeda |
| `usage_records` | tokens, custos, cadeia de fallback, estado, trace_id | sem conteúdo de mensagens |

Redis guarda estado quente: contadores de janela, contadores de orçamento por período, reservas
pendentes (`resv:pending`), estado dos circuitos (`cb:<provider>:<modelo>`).

## Fronteiras de falha

| Falha | Comportamento |
|---|---|
| Redis indisponível | `503 service_unavailable` (fail-closed); `/health/ready` = 503 |
| Postgres indisponível | `/health/ready` = 503; o registo de uso falha mas o pedido já foi servido (erro registado) |
| Um provider falha | fallback para o hop seguinte; circuito abre após a taxa de falhas |
| Todos os providers falham | `503 upstream_unavailable` com a lista de hops |
| Processo morre a meio | reserva expira; sweeper cobra a estimativa |
| Preço em falta | `503 pricing_missing`, provider nunca chamado |

## Limitações conhecidas

- Sem streaming (fase 2).
- Sem Docker neste ambiente: `Dockerfile`, `docker-compose.yml`, `deploy/` e o workflow de CI não
  foram executados; foram validados em sintaxe.
- O teste de 100 pedidos concorrentes com limite RPM 50 passou em Redis real 7.4.11
  (2026-11-24). A prova de orçamento com Redis real continua pendente (ver `docs/learn/07`).
- A estimativa de tokens é aproximada (~4 caracteres por token).
