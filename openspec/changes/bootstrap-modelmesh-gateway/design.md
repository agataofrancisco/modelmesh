# Design

## Context

O repositório está vazio. Motivação: ver `proposal.md`. Requisitos: ver `specs/`. Não há Docker local. Redis e Postgres reais são necessários para provar a atomicidade e ficam em testes marcados e em CI. Pedagogicamente, este projecto ensina sistemas distribuídos aplicados a LLMs: concorrência, atomicidade, falhas parciais e observabilidade.

## Goals / Non-Goals

**Goals:**
- O caminho de um pedido é um pipeline explícito: `auth → policy → rate limit → budget reserve → route (hops) → reconcile → record`.
- Cada decisão de política é **explicável** (cabeçalhos e registo de uso).
- O comportamento sob falha é provado por testes, não descrito.

**Non-Goals:**
- Streaming, embeddings, multi-região e cache semântica.
- Substituir o LiteLLM. O LiteLLM pode ser usado como adaptador de providers, com a fronteira documentada em `docs/decisions.md`.

## Decisions

### D1 — FastAPI assíncrono + httpx
Usa um `AsyncClient` partilhado com pools e timeouts por hop (`httpx.Timeout`). O timeout total é imposto com `asyncio.timeout`.
- *Alternativa:* Go, mais rápido. Rejeitada pela velocidade de desenvolvimento e pela coerência com o resto do portefólio. O overhead é medido.

### D2 — Adaptadores próprios e LiteLLM opcional
Uma interface `ProviderAdapter.chat(request) -> Response | ProviderError`, com adaptadores `openai_compatible` (OpenRouter/OpenAI) e `mock`. Os erros são normalizados para uma taxonomia (`transient`, `client`, `auth`, `timeout`).
- *Porquê:* o policy engine depende desta taxonomia. Se usarmos LiteLLM, fica atrás da mesma interface.

### D3 — Rate limit com scripts Lua no Redis
- RPM: janela deslizante com sorted set (`ZREMRANGEBYSCORE` + `ZCARD` + `ZADD` num script Lua, portanto atómico).
- TPM estimado: contador por janela de minuto com estimativa de tokens (tokenizador aproximado; documentar o erro).
- Concorrência: contador `INCR`/`DECR` com TTL de segurança. O `DECR` está num `finally`.
- *Alternativa:* token bucket. Também é válido. Escolhemos a janela deslizante pela precisão no teste "exactamente 50 de 100". Explicar o trade-off memória vs precisão.

### D4 — Orçamentos: reserva atómica em Redis, verdade em Postgres
Um script Lua verifica `spent + reserved + estimate <= budget` para a chave **e** para a equipa e incrementa `reserved` nas duas, ou nenhuma. A reconciliação faz `reserved -= estimate; spent += real`. Cada reserva tem `reservation:{id}` com TTL. Um *sweeper* liberta as órfãs e regista o evento. O Postgres guarda o registo de uso definitivo; os contadores Redis são reconstruíveis a partir dele no arranque.
- *Estimativa máxima:* `tokens_entrada_estimados * preço_in + max_tokens * preço_out`. É conservadora por design: pode rejeitar pedidos que caberiam, mas nunca deixa ultrapassar o orçamento.
- *Alternativa:* `SELECT ... FOR UPDATE` em Postgres. É correcto, mas tem contenção e latência maiores. Fica discutido no learn.

### D5 — Circuit breaker
Estado em Redis por `(provider, modelo)`, partilhado entre réplicas: `closed`, `open(until)` e `half_open` (um único pedido de teste com `SET NX`). Usa uma janela de contagem de falhas e um limiar configurável.

### D6 — Retries
`min(cap, base * 2^n) * random(0.5, 1.5)` (full/equal jitter, documentado). Respeita `Retry-After`. Nunca ultrapassa o deadline total. Só repete erros `transient`/`timeout`.

### D7 — Preços
Tabela `prices(provider, model, input_per_mtok, output_per_mtok, currency, effective_date, source)`, carregada de YAML para Postgres. Lookup pelo maior `effective_date <= agora`. Os preços reais vêm de config com fonte e data, nunca de constantes no código.

### D8 — Chaves
`mm_live_<32 bytes base62>`. Guarda-se `sha256(chave)` (adequado para segredos aleatórios de alta entropia; explicar porque não é preciso bcrypt) e `prefix` (8 caracteres). As chaves de admin são separadas e definidas por env/seed.

### D9 — Observabilidade
Usa `prometheus-client`, o OpenTelemetry SDK com exportador OTLP opcional e um `deploy/` com configs de Prometheus e Grafana (dashboard JSON). Etiquetas com cardinalidade controlada.

### D10 — Fail-closed
Se o Redis falhar, o gateway rejeita pedidos (`503`) em vez de servir sem limites. Isto é configurável, mas o default é fechado. Tema de entrevista: disponibilidade vs controlo de custos.

### D11 — Documentação pedagógica
`docs/learn/` tem: `00-visao-geral`, `01-api-openai-compativel`, `02-chaves-e-hash`, `03-policy-engine`, `04-retries-backoff-jitter`, `05-circuit-breaker`, `06-rate-limiting-redis-lua`, `07-orcamentos-reserva-reconciliacao`, `08-precos-e-custos`, `09-observabilidade`, `10-chaos-e-benchmark` e `11-perguntas-de-entrevista`.

## Risks / Trade-offs

- [O fakeredis não reproduz a atomicidade real] → Os testes de concorrência só contam como prova com Redis real (`-m redis`). O relatório indica o backend.
- [A estimativa de tokens é imprecisa] → Reserva conservadora com `max_tokens`. O erro de estimativa é medido e documentado.
- [Overhead do proxy] → Medido. Pools de ligação e zero chamadas síncronas no caminho crítico.
- [O estado do circuito no Redis acrescenta uma chamada por pedido] → É aceitável; medido no benchmark.
- [Sem Docker, não há stack Grafana local] → Configs entregues e marcadas "não testado localmente".

## Migration Plan

Projecto novo. Migrações Alembic e seed de equipas, preços e políticas demo. Deploy documentado: gateway em containers com Redis e Postgres geridos. O endpoint `/metrics` fica acessível apenas na rede privada.

## Open Questions

- Que providers reais usar na validação opcional? Não altera o desenho.
