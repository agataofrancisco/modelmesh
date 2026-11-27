# Estudo de caso: ModelMesh

## Contexto

A equipa de plataforma da Órbita Tech (tenant fictício `orbita`) serve três equipas internas:
`suporte`, `marketing` e `dados`. Cada uma usa LLMs com chaves próprias, sem limites e sem uma visão
consolidada de custo. Quando um provider falha, as aplicações falham com ele.

## Problema

- Custo desconhecido por equipa e sem teto.
- Dependência direta de um provider, sem fallback.
- Sem prova de que o comportamento sob falha é o desejado.

## Solução

Um gateway compatível com a OpenAI, com:

- chaves virtuais por equipa (hash, revogação imediata, administração separada);
- política declarativa com alias de classe e cadeia de fallback limitada;
- circuit breaker partilhado, retries com jitter e deadline total;
- rate limit e orçamento atómicos em Redis, com reconciliação no Postgres;
- métricas, tracing e painel de administração;
- chaos com asserções e um benchmark de overhead.

## Resultados verificados

- Na execução anterior, 56 testes passaram e 1 foi ignorado por falta de Redis real.
  Em 2026-11-24, a prova isolada contra Redis 7.4.11 passou: `1 passed, 56 deselected in 4.48s`.
  O teste enviou 100 pedidos concorrentes com RPM 50 e confirmou exatamente 50 admissões.
- Os 8 cenários de chaos passam. Com 200 pedidos concorrentes e orçamento de 1 USD, o gasto final
  foi 0,99 USD, com 194 pedidos rejeitados com `402`.
- No painel, sob falha forçada do mock A, os três primeiros pedidos fizeram fallback para B e, depois
  de o circuito abrir, os seguintes foram diretamente para B.
- Benchmark (mock, localhost, não é produção): sobrecarga de +218 ms no p50 do gateway face ao
  directo, dominada por fakeredis e SQLite nesta máquina.

## O que não está provado

- Orçamento com Redis real e Redis + Postgres reais sob carga: pendentes. A prova de RPM 50/100
  foi executada apenas contra Redis real.
- Stack Docker verificada em 2026-11-27: 8 serviços, chat completion 200 via gateway, Grafana e Prometheus 200. A verificação revelou e corrigiu dois defeitos (healthcheck herdado pelos mocks e seed demo em falta).
- Providers reais: não testados; apenas mocks.

## Próximos passos

1. Correr a prova de orçamento com Redis real e medir o benchmark com Redis e Postgres reais.
2. Medir o benchmark de overhead dentro da stack Docker (Redis e Postgres reais).
3. Revisão de segurança independente e análise de dependências.
4. Validação opcional com providers reais e gravação de GIF do painel.
