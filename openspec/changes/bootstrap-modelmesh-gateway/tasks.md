# Tasks

## 1. Fundações

- [ ] 1.1 Criar a estrutura `gateway/app/{api,auth,policy,limits,budget,providers,accounting,observability,store}`, `frontend/`, `migrations/`, `chaos/`, `bench/`, `deploy/` e `docs/learn/`; verificar com `git status`
- [ ] 1.2 Confirmar e fixar versões (FastAPI, Pydantic v2, httpx, redis, SQLAlchemy, Alembic, prometheus-client, opentelemetry, pytest, pytest-asyncio, fakeredis, Ruff); verificar a instalação num venv limpo
- [ ] 1.3 `Settings`, `.env.example`, `/health/live`, Ruff e pytest; verificar que passam
- [ ] 1.4 Escrever `docs/learn/00-visao-geral.md` com o diagrama de sequência Mermaid de um pedido; verificar que corresponde aos módulos

## 2. Dados, chaves e administração

- [ ] 2.1 Criar modelos e migrações (`teams`, `keys`, `policies`, `prices`, `usage_records`) e o seed demo; verificar com `alembic upgrade head` e um teste de seed
- [ ] 2.2 Implementar a emissão/hash/prefixo/revogação de chaves e as credenciais de admin separadas; verificar com testes de chave mostrada uma vez, revogada → 401 e chave de inferência no admin → 403
- [ ] 2.3 Implementar `POST /admin/teams`, `POST /admin/keys` e `PUT /admin/policies/{team}` com validação; verificar com teste de política inválida → 422 e manutenção da anterior
- [ ] 2.4 Escrever `docs/learn/02-chaves-e-hash.md`; verificar que os exemplos correspondem ao código

## 3. Providers e API de inferência

- [ ] 3.1 Implementar a interface de adaptador, a taxonomia de erros, o adaptador `openai_compatible` e os mocks A/B configuráveis; verificar com testes de cada tipo de falha simulada
- [ ] 3.2 Implementar `POST /v1/chat/completions` (validação, formato de erro OpenAI, request_id, cabeçalhos `x-modelmesh-*`); verificar com teste que usa o SDK oficial da OpenAI apontado ao gateway com o mock
- [ ] 3.3 Escrever `docs/learn/01-api-openai-compativel.md`; verificar com o exemplo do SDK a correr

## 4. Policy engine e resiliência

- [ ] 4.1 Implementar a resolução de política (aliases de classe, modelos permitidos, cadeias); verificar com testes de `model_not_allowed` e resolução `cheap`
- [ ] 4.2 Implementar retries com backoff + jitter, `Retry-After` e deadline total; verificar com testes de tempo controlado (relógio falso)
- [ ] 4.3 Implementar o fallback limitado com distinção entre erro transitório e erro de cliente; verificar com testes A→B, 400 sem fallback e todos a falhar → 503
- [ ] 4.4 Implementar o circuit breaker em Redis (closed/open/half-open); verificar com testes de abertura, salto e recuperação
- [ ] 4.5 Escrever `docs/learn/03-policy-engine.md`, `04-retries-backoff-jitter.md` e `05-circuit-breaker.md`; verificar que cada diagrama de estados tem um teste correspondente

## 5. Limites e orçamentos

- [ ] 5.1 Implementar o rate limit RPM/TPM/concorrência com scripts Lua; verificar com o teste de 100 pedidos concorrentes → exactamente 50 aceites em Redis real (`-m redis`)
- [ ] 5.2 Implementar a reserva/reconciliação atómica de orçamento (chave + equipa), a libertação em falha e o sweeper de órfãs; verificar com testes de usage ausente, pedido falhado e crash simulado
- [ ] 5.3 Implementar o fail-closed quando o Redis não está disponível; verificar com teste → 503 e `/health/ready` em 503
- [ ] 5.4 Escrever `docs/learn/06-rate-limiting-redis-lua.md` e `07-orcamentos-reserva-reconciliacao.md` (incluindo a race condition que a atomicidade evita, com o teste que a demonstra); verificar a referência ao teste

## 6. Contabilidade

- [ ] 6.1 Implementar o carregamento de preços versionados e o cálculo de custo por `effective_date`; verificar com testes de mudança de preço e `pricing_missing`
- [ ] 6.2 Implementar o registo de uso com redacção e `GET /admin/usage` com agregações; verificar com testes de que email/telefone não aparecem e de agregação por equipa
- [ ] 6.3 Escrever `docs/learn/08-precos-e-custos.md`; verificar o exemplo de cálculo com um teste

## 7. Observabilidade e painel

- [ ] 7.1 Implementar as métricas Prometheus com etiquetas controladas e o tracing OTel com propagação de `traceparent`; verificar com testes de `fallback_total` e de trace partilhado
- [ ] 7.2 Completar `/health/ready` e `GET /admin/routes`; verificar com testes
- [ ] 7.3 Criar `deploy/` com Prometheus e o dashboard Grafana (JSON); verificar a sintaxe e marcar como não testado localmente
- [ ] 7.4 Criar o painel React (equipas, chaves, orçamentos, políticas, consumo, p50/p95, erros, circuitos, testador de failover); verificar no browser o fluxo do testador
- [ ] 7.5 Escrever `docs/learn/09-observabilidade.md`; verificar que as métricas citadas existem

## 8. Chaos e benchmark

- [ ] 8.1 Implementar o script de chaos com os 8 cenários e as asserções; verificar que todos passam com Redis real, ou registar a pendência
- [ ] 8.2 Implementar o benchmark de overhead (directo vs gateway, com e sem fallback) e o relatório com hardware/data/commit; verificar que gera o relatório com valores medidos
- [ ] 8.3 Escrever `docs/learn/10-chaos-e-benchmark.md` com os resultados obtidos; verificar que os números vêm do relatório

## 9. Entrega e integração

- [ ] 9.1 Dockerfile, `docker-compose.yml` (gateway, redis, postgres, prometheus, grafana, mocks) e CI (Ruff, pytest, testes redis/postgres com services, chaos, build do frontend); verificar a validade do workflow
- [ ] 9.2 `README.md`, `docs/architecture.md`, `docs/decisions.md` (incluindo o que é do ModelMesh vs do LiteLLM) e `docs/case-study.md`; verificar que os comandos correm
- [ ] 9.3 `docs/learn/11-perguntas-de-entrevista.md` (≥25 perguntas); verificar a consistência com o código
- [ ] 9.4 Revisão de segurança (chaves, admin, proxy aberto, redacção, fail-closed); verificar que os achados estão resolvidos ou documentados

## Workflow follow-up

- Validação opcional com providers reais e GIF do painel.
- Arquivar a change antes de iniciar `add-cost-autopilot`.
