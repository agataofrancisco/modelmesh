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

- 56 testes passam e 1 é ignorado (Redis real indisponível). A execução completa está no fim deste
  documento.
- Os 8 cenários de chaos passam. Com 200 pedidos concorrentes e orçamento de 1 USD, o gasto final
  foi 0,99 USD, com 194 pedidos rejeitados com `402`.
- No painel, sob falha forçada do mock A, os três primeiros pedidos fizeram fallback para B e, depois
  de o circuito abrir, os seguintes foram diretamente para B.
- Benchmark (mock, localhost, não é produção): sobrecarga de +218 ms no p50 do gateway face ao
  directo, dominada por fakeredis e SQLite nesta máquina.

## O que não está provado

- Comportamento com Redis real e Postgres real sob carga: pendente, a prova em Redis real não foi
  corrida neste ambiente.
- Stack Prometheus/Grafana e imagem Docker: não testados localmente (sem Docker).
- Providers reais: não testados; apenas mocks.

## Próximos passos

1. Correr as provas de concorrência com Redis real (`MODELMESH_TEST_REDIS_URL`) e medir o benchmark
   com Redis e Postgres reais.
2. Validar o stack com Docker (imagem, compose, Prometheus, Grafana).
3. Revisão de segurança independente e análise de dependências.
4. Validação opcional com providers reais e gravação de GIF do painel.
