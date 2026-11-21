# 04 · Retries, backoff e jitter

## O problema

Erros transitórios (429, 5xx, timeouts) costumam desaparecer em segundos. Repetir logo, em
uníssono, com todos os clientes ao mesmo tempo, pode derrubar um provider que já estava em
dificuldades (efeito de manada).

## O que entra e o que sai

Entra uma falha normalizada (`ProviderError`, com `kind` e `retry_after_s`). Sai uma decisão:
repetir após um atraso, ou passar ao hop seguinte. O atraso é calculado por
`gateway/app/policy/backoff.py:backoff_delay_s`:

```text
delay(n) = min(cap, base * 2^n) * U(0.5, 1.5)
se Retry-After existe: delay = max(delay, Retry-After)
```

Com `base=0.2 s` e `cap=2 s` (`settings.py`), o atraso esperado é 0.2, 0.4, 0.8, 1.6 s, com ±50%.

## Como funciona por dentro

- Só `transient` e `timeout` são repetidos (`providers/base.py:RETRYABLE_KINDS`). `auth`,
  `invalid_response` e `client` não são repetidos no mesmo hop.
- `RouteExecutor.run` (`gateway/app/policy/executor.py`) compara o atraso com o tempo restante do
  deadline total (`backoff.py:Deadline`). Se esperar excederia o deadline, não espera: passa ao
  hop seguinte.
- O relógio é injetado (`gateway/app/clock.py`). `FakeClock.sleep` avança o tempo sem esperar,
  por isso os testes são determinísticos e rápidos.

## Porquê esta escolha

- **Jitter**: sem jitter, todas as repetições coincidem e voltam a sobrecarregar o provider.
- **Retry-After respeitado**: o provider sabe quando pode receber de novo; ignorá-lo seria
  insistir numa resposta de rate limit.
- **Deadline primeiro**: o cliente tem um tempo total. Uma repetição que o ultrapassa só desperdiça.

## Alternativas

- Jitter total (`U(0, cap)`): menos previsível, mais espalhado; escolhemos o intervalo relativo para
  manter o crescimento exponencial visível.
- Circuit breaker sem retries: mais simples, mas perde recuperações rápidas de falhas isoladas.

## Como falha

- Atraso dentro da banda de jitter: `test_backoff_grows_exponentially_within_jitter_band`.
- `Retry-After` como mínimo: `test_backoff_respects_retry_after_minimum`.
- Deadline com relógio falso: `test_deadline_uses_injected_clock`.
- Fim de deadline por fallback: `test_slow_provider_times_out_and_falls_back`.

## Perguntas de entrevista

1. **Porque é que o jitter é relativo ao exponencial?** Mantém o crescimento do atraso previsível
   e ainda dispersa as repetições. Em produção, mede-se a dispersão antes de escolher.
2. **O que é um retry storm?** Repetições em cascata de muitos clientes ao mesmo provider. Mitiga-se
   com backoff, jitter e com um circuit breaker partilhado.
3. **Porque se respeita o deadline e não só o número de tentativas?** O número de tentativas limita
   o custo; o deadline limita a latência que o cliente vê.
