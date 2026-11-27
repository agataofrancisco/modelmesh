# PROMPT 03 — ModelMesh: gateway LLM multi-provider com failover real

## Missão
Implementa uma porta de entrada OpenAI-compatible para aplicações empresariais consumirem LLMs de forma controlada. O produto oferece autenticação por equipa, política de encaminhamento, quotas, budgets, failover e observabilidade. Diferencia da funcionalidade já disponível em LiteLLM: apresenta um **policy engine próprio e testes de chaos engineering**, sem reimplementar indiscriminadamente bibliotecas maduras.

## Stack e desenho
Python FastAPI (preferência pela velocidade de desenvolvimento) com Redis para limites atómicos e cache, PostgreSQL para equipas/chaves políticas/balancos históricos, Prometheus + OpenTelemetry + Grafana para métricas. Provider adapters para OpenRouter/OpenAI-compatible e `mock_provider_a/b` que simulam timeout, HTTP 429, 5xx, latência, falha de JSON e streaming. É permitido usar LiteLLM como camada de protocolos/provider normalization se compatível com licença e funcionalidades OSS da versão instalada; documenta exactamente que capacidade é tua vs da dependência.

## Funcionalidades
- `POST /v1/chat/completions` para JSON de texto (streaming SSE fase 2); autenticação por chaves virtuais com HASH em repouso; tenant isolado; RBAC no painel.
- Policy engine: allowed models per team, tasks `cheap`/`balanced`/`critical`, model/cost preference, fallback chains limitadas, circuit breaker com cooldown, retries só para erros transitórios, backoff+jitter e timeouts per hop.
- Rate limit atomicizado em Redis (RPM e estimativa TPM); budget por team e por key com reserva atómica estimada ANTES do pedido e reconciliação após uso real. Rejeitar ao exceder teto; limite também de concorrência; mostrar comportamento perante crashes/usage ausente.
- Custos por tokens com tabela de preços `effective_date`, moeda e fonte; preços do modelo configuráveis, nunca números hardcoded assumidos eternamente. Registrar prompt tokens, completion tokens, custo estimado/real, provider, fallback path e latency com redacção de dados privados.
- Observabilidade: métricas `request_total`, `errors_by_reason`, `fallback_total`, `rate_limit_rejections`, `budget_rejections`, `token_usage`, `estimated_spend`, `latency_histogram`; tracing com trace_id propagado, endpoint de métricas protegido conforme deployment.

## Experiência
UI com equipas, chaves (mostrar apenas uma vez), budgets, consumo, distribuição de modelos, latência p50/p95, erros por provedor e testador de failover. Gestão admin separada de chave de inferência.

## API mínima
`POST /v1/chat/completions`, `GET /health/live`, `GET /health/ready`, `GET /metrics`, `POST /admin/teams`, `POST /admin/keys`, `PUT /admin/policies/{team}`, `GET /admin/usage`, `GET /admin/routes`. Especificação OpenAPI e exemplos de SDK client.

## Testes demonstráveis
Testa 100 pedidos concorrentes ao limite, vários 429/5xx, provedor A falha→B atende, ambos falham→erro coerente, budget de 1 USD em concorrência (com preços fictícios nos mocks), inexact usage reconciliation e privacy. Faz benchmark com perfis iguais, documentando overhead do proxy, latência com/sem fallback e zero bypass de budget em testes. Implementa chaos scenario script e mostra GIF de painel. Nunca exponhas open proxy sem auth nem chaves de terceiros.

## Regras de execução (obrigatórias)
És um agente sénior de software engineering e AI engineering. A tua missão é IMPLEMENTAR código funcional neste repositório, não apenas escrever um plano ou pseudocódigo. Primeiro inspecciona o repositório; depois propõe em `IMPLEMENTATION_PLAN.md` um plano curto e segue-o por fases até teres uma versão executável. Não pares após criar ficheiros vazios. Usa documentação oficial actual das bibliotecas e fixa versões compatíveis; não inventes APIs nem dependências. Caso não tenhas acesso a rede/credenciais, implementa adaptadores, mocks determinísticos e testes locais, mas distingue explicitamente o que foi testado de verdade do que foi apenas preparado.

Normas comuns: Python 3.11+ (salvo indicação explícita), tipagem, Pydantic v2, configuração por `.env.example`, FastAPI com OpenAPI, Ruff, pytest, logging estruturado sem secrets/PII, Dockerfile, `docker-compose.yml` quando fizer sentido, healthcheck e README claro (arranque, decisões de arquitectura, ameaças, limitações, custos, credenciais e deploy). Não coloques chaves no cliente ou no Git; valida entradas, implementa timeouts/retries limitados e autenticacao para operações administrativas. Inclui modo DEMO com dados sintéticos e sem pagamento; implementa testes unitários e testes de integração determinísticos em CI, mais uma suite de integração real opcional. Escreve `docs/architecture.md`, `docs/decisions.md`, `docs/case-study.md` com métricas REAIS ou campos `TODO: medir` (nunca inventes resultados). Entrega exactamente os comandos de execução e testes e lista limitações.

Para deployment, prepara backend persistente numa VM/serviço de containers e frontend estático quando possível; não assumes que Vercel Functions suporta Redis, workers long-running, volumes persistentes ou treino GPU. Se houver persistência, usa serviço gerido/volume externo e documenta credenciais, migrações e backups. Antes de concluir, executa testes, corrige falhas, regista o output e documenta o que não foi possível executar.
