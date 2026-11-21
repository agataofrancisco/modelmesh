# 10 · Chaos e benchmark

## O problema

Descrever o comportamento sob falha não prova nada. É preciso provocar as falhas e verificar, com
uma asserção automática, que o gateway se comporta como a spec diz. E medir o custo do proxy com
números, não com estimativas.

## O que entra e o que sai

**Chaos** (`chaos/run_chaos.py`): oito cenários, cada um com uma asserção. Sai um relatório
(`chaos/results/chaos-report.json`) e o código de saída é `1` se algum falhar.

Resultado real da última execução (`providers: mock`):

```text
[PASS] A falha -> B responde: status=200 path=mock_a->mock_b
[PASS] Ambos falham -> 503 com request_id: status=503
[PASS] Tempestade de 429: status_codes=[503]
[PASS] Provider lento: status=200 elapsed_ms=313
[PASS] JSON inválido: status=200
[PASS] Usage ausente: status=200
[PASS] Redis indisponível (fail-closed): status=503
[PASS] Orçamento de 1 USD sob 200 pedidos concorrentes: accepted=6 rejected_402=194 spent_usd=0.990000
providers=mock redis=fakeredis em processo (FakeAsyncRedis com Lua via lupa); não é Redis real all_passed=True
```

Nota sobre a "Tempestade de 429": o cenário configura 429 nos dois providers. O gateway devolve
`503 upstream_unavailable` com o envelope, porque a cadeia esgotou; aceita-se 200, 429 ou 503,
todos com envelope. Um 429 "puro" só aparece se a cadeia tiver um único hop.

**Benchmark** (`bench/bench_overhead.py`): HTTP real em localhost, providers mock, 300 pedidos por
cenário, concorrência 8, aquecimento de 30 pedidos. Resultados medidos (`bench/results/overhead-report.json`):

| Cenário | p50 (ms) | p95 (ms) | p99 (ms) |
|---|---|---|---|
| Directo ao mock A | 134,4 | 314,8 | 384,9 |
| Gateway sem fallback | 352,5 | 1086,9 | 1587,8 |
| Gateway com fallback (A falha) | 508,9 | 1782,5 | 2717,9 |

Sobrecarga do gateway sem fallback: +218 ms no p50, +772 ms no p95 e +1203 ms no p99.

**Interpretação honesta**: estes números **não** são o custo real de um gateway em produção. O
gateway corre aqui com fakeredis em processo (Lua em Python via lupa, lento) e com SQLite via
aiosqlite (uma thread por consulta), e faz várias consultas por pedido. A maior parte da sobrecarga
vem daí, não do proxy em si. Ficam como `TODO: medir` com Redis real e Postgres real, em hardware
dedicado.

## Como funciona por dentro

- Chaos: os cenários usam `tests/conftest.py:build_env`, com transporte ASGI em processo para os
  mocks e o gateway. Não há sockets, por isso o chaos é determinístico, mas não mede rede.
- Cada cenário tem a sua pasta de base de dados (`chaos/run_chaos.py:run_all`), para não haver
  estado partilhado entre cenários.
- Benchmark: uvicorn em threads (`tests/live_support.py:ThreadServer`), cliente `httpx.AsyncClient`
  com concorrência limitada por `asyncio.Semaphore`. O relatório inclui plataforma, versão do
  Python, data UTC e o commit.

## Porquê esta escolha

- Asserções nos cenários transformam "funciona" em algo que o CI pode reprovar.
- Medir directo ao mock e ao gateway com a mesma carga isola o custo do proxy.
- Publicar limitações junto dos números evita que se extrapole para providers reais.

## Alternativas

- Chaos com Toxiproxy ou tc/netem: mais realista na rede, mas exige Docker/Linux (não disponível aqui).
- Benchmark com `wrk` ou `k6`: melhores geradores de carga, exigem instalação externa.

## Como falha

- Cada cenário falha com exit 1 se a asserção não se cumprir (`chaos/run_chaos.py:main`).
- Um cenário que lança excepção conta como falha, não é ignorado.

## Limitações conhecidas

- Providers mock; latências são simuladas.
- Sem Redis real; cenários de concorrência usam fakeredis (com rótulo no relatório).
- Sem Docker: nada disto correu contra o stack Prometheus/Grafana.
- A medição foi feita numa só máquina (Windows 11, Python 3.12.10), com ruído do sistema.

## Perguntas de entrevista

1. **Porque é que um chaos com asserção é mais útil do que um teste unitário de erro?** Porque
   testa a composição (circuito + fallback + orçamento) sob carga, não cada peça isolada.
2. **Porque é que p99 importa mais que a média?** Porque o utilizador que cai na cauda sente o
   sistema lento. A média esconde-a.
3. **Porque é que o benchmark reporta a sobrecarga e não só a latência do gateway?** A sobrecarga
   é a diferença com a mesma carga directa; é ela que mostra o custo do proxy.
