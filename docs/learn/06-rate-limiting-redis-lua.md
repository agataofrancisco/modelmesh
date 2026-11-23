# 06 · Rate limiting atómico com Redis e Lua

## O problema

Uma chave tem 50 pedidos por minuto. Cem pedidos chegam ao mesmo instante, a duas réplicas
diferentes. Se cada réplica fizer "ler contador, decidir, escrever", as duas leem 49 e aceitam
mais 49: passam 98 pedidos. Esta é a condição de corrida clássica de leitura-modificação-escrita.

## O que entra e o que sai

Entram o âmbito da chave e o da equipa (`ScopeLimits`), a estimativa de tokens e um identificador
do pedido. Sai um `Lease` (se aceite) ou `RateLimitDenied` com o motivo e o `retry_after_ms`.
Os motivos são `rpm`, `tpm` e `concurrency`, para a chave e para a equipa.

## Como funciona por dentro

- `gateway/app/limits/lua/acquire.lua` faz a verificação dos seis limites e só depois o
  incremento. Um script Lua corre atomicamente no Redis: nenhum comando de outro cliente se
  intercala.
- RPM: janela deslizante com `ZSET` (`ZREMRANGEBYSCORE` remove o que saiu da janela, `ZCARD` conta,
  `ZADD` regista).
- TPM: contador por minuto (`rl:<âmbito>:tpm:<minuto>`), incrementado pela estimativa de entrada
  mais `max_tokens`.
- Concorrência: cada pedido recebe um membro único num sorted set `:conc:v2`. O script usa `TIME`
  do Redis como relógio, remove leases vencidos, verifica ambos os âmbitos e adiciona o lease
  atomicamente. A pontuação é o instante de expiração; a chave expira no maior score para que uma
  réplica com TTL mais curto não apague leases mais longos. `release.lua` remove apenas o membro
  daquele pedido. Se o processo morrer, o lease expira sem libertar o lease de outro pedido.
- Redis 7 é necessário para usar `TIME` em Lua com replicação determinística de efeitos; Compose e
  CI fixam `redis:7`.
- `:conc:v2` usa um pool separado do contador antigo. O rollout deve parar admissão, drenar todos
  os pedidos e retirar todas as réplicas antigas antes de activar v2. No rollback, parar admissão,
  drenar v2 e retirar todas as réplicas v2 antes de reactivar a versão antiga. Um marcador apenas
  em runtime não consegue vedar o split-brain de limites entre versões mistas.

Teste com a concorrência real do mesmo código (fakeredis em processo, Lua real via lupa):
`tests/integration/test_limits_budget.py::test_rpm_100_concurrent_exactly_50_accepted` → 50
aceites e 50 com `429`.

Teste com sockets reais de redis-py contra um servidor fakeredis TCP:
`tests/integration/test_fakeredis_tcp.py::test_100_concurrent_over_tcp_fakeredis_exactly_50`.
**Rotulado: fakeredis TCP server, não é Redis real.**

Teste com Redis real: `tests/integration/test_fakeredis_tcp.py::test_100_concurrent_real_redis_exactly_50`,
marcado `redis` (apesar do nome do módulo conter `fakeredis`, este caso usa a URL
`MODELMESH_TEST_REDIS_URL` e liga-se a um servidor Redis real). **Ignorado neste ambiente** porque
não há Redis real acessível: `SKIPPED ... Redis real indisponível`. Pendente.

## Porquê esta escolha

- **Lua em vez de transações**: `MULTI/EXEC` não permite decidir com base em valores lidos no
  mesmo bloco. Lua sim, e um script é uma unidade atómica.
- **Janela deslizante em vez de janela fixa**: a janela fixa permite 2x o limite na fronteira do
  minuto. A janela deslizante é exacta, ao custo de memória (uma entrada por pedido na janela).
- **Pedido rejeitado não conta**: senão um cliente agressivo esgotava o próprio limite com
  tentativas recusadas.
- **Verificação de todos os âmbitos antes de incrementar**: se a chave passasse e a equipa
  recusasse, a chave teria ficado com um incremento fantasma.

## Alternativas

- Token bucket: também correto; a janela deslizante foi escolhida pela precisão do teste "exactamente
  50 de 100".
- `SELECT ... FOR UPDATE` no Postgres: correto, mas com contenção e latência maiores no caminho
  crítico.

## Como falha

- Redis indisponível: `503 service_unavailable` (fail-closed, `test_redis_down_fails_closed_with_503`).
- Concorrência libertada mesmo com erro: `test_concurrency_limit_released_even_on_error`.
- Limite de TPM: `test_tpm_limit_rejects_when_minute_budget_spent`.

## Perguntas de entrevista

1. **Porque é que a corrida acontece mesmo com um único Redis?** Porque a aplicação lê e escreve
   em comandos separados. Atomicidade exige que a decisão e a escrita estejam no mesmo comando ou
   script no servidor.
2. **Porque é que o TPM é estimado à entrada?** A saída só se conhece depois. Reservamos
   `max_tokens` para ser conservadores. O erro de estimativa é documentado em `08-precos-e-custos.md`.
3. **O que acontece se o processo morrer com um lease ativo?** A remoção no `finally` não corre,
   mas a pontuação do lease expira e o próximo acquire remove-o sem afectar os outros membros.
