# 07 · Orçamentos: reserva, reconciliação e órfãs

## O problema

Orçamento de 1 USD. Duzentos pedidos chegam em simultâneo. Cada um confere "gasto atual < 1" antes
de chamar o provider. Todos veem 0 e todos avançam. O gasto real acaba muito acima de 1 USD.
Esta é a mesma corrida do `06`, mas com dinheiro.

## O que entra e o que sai

Entram a estimativa máxima do pedido (micro-USD), os limites da chave e da equipa e um payload
pequeno para o registo. Sai uma `Reservation` ou `BudgetExceeded` (`402 budget_exceeded`, com o
âmbito que falhou). Depois do provider, a reserva é reconciliada pelo custo real.

Resultado medido no cenário de chaos (`chaos/results/chaos-report.json`, `providers: mock`):

```text
[PASS] Orçamento de 1 USD sob 200 pedidos concorrentes: accepted=6 rejected_402=194 spent_usd=0.990000
```

## Como funciona por dentro

- `gateway/app/budget/lua/reserve.lua`: verifica `spent + reserved + estimate <= budget` para a
  chave e para a equipa; se ambas passam, incrementa `reserved` nas duas e guarda a reserva.
- `gateway/app/budget/lua/settle.lua`: troca a reserva pelo custo real (`real=0` para libertar em
  falha). É idempotente: se a reserva já não existe, não faz nada.
- Estimativa máxima (`gateway/app/pipeline.py:handle`): para cada hop da cadeia, custo de
  `estimate_in` mais `max_tokens` ao preço vigente; usa-se o **máximo** dos hops, porque o fallback
  pode servir qualquer um.
- Período mensal UTC (`YYYYMM`). Contadores em micro-USD inteiros, para que `INCRBY` seja exacto.
- Sweeper (`gateway/app/budget/sweeper.py`): reservas com TTL expirado (`resv:pending`, um ZSET
  com a data de expiração) são reconciliadas pela estimativa e registadas com
  `status=orphan_released` e o evento `orphan_reservation_released`.

```mermaid
flowchart LR
    A[Pedido] --> R{reserve.lua}
    R -- excede --> X[402 budget_exceeded]
    R -- ok --> P[Provider]
    P -- sucesso com usage --> S[settle: custo real]
    P -- sucesso sem usage --> E[settle: estimativa do hop servido]
    P -- falha --> F[settle: 0 (libertar)]
    P -. crash .-> O[Sweeper após TTL: settle com estimativa]
```

## Porquê esta escolha

- **Reserva antes da chamada**: é a única forma de garantir que o orçamento não é ultrapassado sob
  concorrência. Reconciliar depois não impede nada.
- **Estimativa conservadora**: se o provider gastar mais do que o `max_tokens`, o excesso não é
  coberto. Com o limite de `max_tokens` no pedido, o pior caso é conhecido.
- **Verdade em Postgres**: o Redis pode perder-se. No arranque, `rebuild_spent` reconstrói o gasto
  do mês a partir de `usage_records` (com `SET NX`, para não sobrescrever reservas em curso).
- **Arredondamento**: custos arredondam para cima, limites para baixo. O erro favorece sempre o
  orçamento.

## Alternativas

- `SELECT ... FOR UPDATE` no Postgres: correto e mais simples de raciocinar, com contenção no mesmo
  registo de orçamento e latência maior.
- Cobrar só depois, sem reserva: o orçamento é ultrapassado sob carga.

## Como falha (com as provas)

- Corrida de 200 pedidos: `test_200_concurrent_requests_never_exceed_budget` (fakeredis em
  processo) e o cenário de chaos acima. Sem a reserva atómica, o gasto excederia 1 USD.
- Pedido falhado liberta a reserva: `test_failed_request_releases_budget_reservation`.
- Reserva órfã após TTL: `test_orphan_reservation_expires_and_is_recorded`.
- Reconciliação idempotente: `test_reserve_settle_and_release_roundtrip`.
- Limite da equipa com a chave livre: `test_budget_over_team_limit_rejected`.

**Pendente**: a mesma prova em Redis real (`MODELMESH_TEST_REDIS_URL`) não foi corrida, porque não
há Redis real neste ambiente.

## Perguntas de entrevista

1. **O que acontece se o provider cobrar mais do que a estimativa?** O orçamento pode ser excedido
   nesse pedido. Por isso o `max_tokens` é limitado pela política e a estimativa é conservadora.
2. **Porque o sweeper cobra a estimativa e não zero?** Um pedido que morreu depois de chamar o
   provider pode ter gasto tokens. Cobrar zero seria subcontar.
3. **Porque há duas réplicas com a mesma reserva?** Não há: a reserva é uma chave Redis única com
   `reservation_id`. Duas réplicas partilham o mesmo contador.
