# 11 · Perguntas de entrevista

Cada resposta aponta para o código ou o teste que a sustenta. Onde a resposta depende de algo não
medido, diz-se isso.

## Arquitetura e API

1. **Porque FastAPI e httpx assíncronos?** Um pedido gasta quase todo o tempo à espera do provider.
   `async` permite milhares de esperas simultâneas com poucos processos. Ver `gateway/app/main.py`.
2. **Porque um pipeline explícito?** Cada etapa tem um motivo e um span. Ver `00-visao-geral.md`.
3. **Porque compatível com a OpenAI?** Adoção: o SDK muda só o `base_url`. Ver `01`.
4. **Porque adaptadores próprios em vez de LiteLLM como núcleo?** O policy engine e os orçamentos
   atómicos são o diferencial; o LiteLLM fica como possível adaptador. Ver `docs/decisions.md`.
5. **O que é um alias de classe?** Um nome estável (`cheap`) que a política resolve para um modelo.
   Permite trocar o modelo sem mudar as aplicações.

## Segurança

6. **Porque é que a chave não é guardada em claro?** Se a base vazar, as chaves não servem. Ver `02`.
7. **Porque SHA-256 e não bcrypt?** Entropia alta do segredo; o custo só atrasaria cada pedido.
8. **Porque admin separado de inferência?** Separação de privilégios: `403` explícito quando se
   usa a chave errada (`test_inference_key_cannot_access_admin`).
9. **Como se revoga uma chave?** Estado na base, consultado a cada pedido. Imediato, com o custo de
   uma consulta por pedido.
10. **O que é fail-closed e porque é o default?** Sem Redis não há limites nem orçamento verificável;
    recusar é mais seguro do que servir sem controlo. Teste: `test_redis_down_fails_closed_with_503`.
11. **Como se evita um proxy aberto?** Cada pedido exige uma chave ativa; sem chave, `401` antes de
    qualquer provider (`test_no_key_is_401_and_never_contacts_provider`).
12. **Que dados ficam nos registos de uso?** Tokens, custos, modelo, equipa, prefixo da chave e
    estado. Nunca mensagens (`test_usage_record_has_no_message_content_and_aggregates`).

## Resiliência

13. **Porque o fallback não repete erros de cliente?** O erro é do pedido; a outra cadeia faria o
    mesmo. Ver `03`.
14. **Porque backoff com jitter?** Evita o efeito de manada em repetições sincronizadas. Ver `04`.
15. **Porque um circuit breaker além dos retries?** Os retries recuperam falhas isoladas; o circuito
    evita que cada pedido pague o timeout de um provider morto. Ver `05`.
16. **Porque o estado do circuito está em Redis?** Para ser partilhado entre réplicas. Custo: uma
    chamada Lua por hop.
17. **Porque um só probe em half-open?** Para não sobrecarregar um provider ainda instável ao
    recuperar.
18. **Como se limita a latência total?** Um deadline medido com o relógio injetado; cada hop recebe
    `min(timeout do hop, restante)`.

## Limites e orçamentos

19. **Porque Lua no Redis?** Atomicidade: decidir e escrever num único script. Ver `06`.
20. **Porque janela deslizante?** A janela fixa permite o dobro do limite na fronteira do minuto.
21. **Como se evita que 200 pedidos excedam um orçamento?** Reserva atómica antes do provider.
    Prova: `chaos/results/chaos-report.json`, spent 0,99 USD com 194 rejeições. Ver `07`.
22. **O que acontece a uma reserva se o processo morrer?** O TTL expira e o sweeper cobra a
    estimativa, registando `orphan_released` (`test_orphan_reservation_expires_and_is_recorded`).
23. **Porque micro-USD inteiros?** Contadores exactos em Redis, sem erro de vírgula flutuante. Ver `08`.
24. **Porque o custo arredonda para cima?** Erro conservador para o orçamento.
25. **Como se reconstrói Redis depois de uma perda?** A partir de `usage_records` no Postgres, com
    `SET NX` (`BudgetLedger.rebuild_spent`).

## Dados e operação

26. **Porque Postgres e não só Redis?** O Redis é rápido mas volátil; o registo de uso e os preços
    têm de sobreviver. Redis é a cache quente; Postgres é a verdade.
27. **Porque preços com `effective_date`?** Histórico auditável; uma mudança não reescreve o passado.
28. **Como se sabe que o Postgres real funciona?** Os testes com `-m postgres` arrancam um PostgreSQL
    16.2 real com pgserver e correm as migrações e um pedido completo.
29. **O que é o `traceparent` e para que serve?** O W3C trace context; liga o trace do cliente ao
    do gateway. Teste: `test_fallback_counted_and_traceparent_shared`.
30. **Porque não `request_id` como etiqueta de métrica?** Cardinalidade: cada valor é uma série nova.
    Ver `09`.
31. **Como se mede o overhead de um proxy?** Mesma carga directa ao backend e através do proxy; a
    diferença é o custo. Ver `10`.
32. **Porque os números do benchmark não são de produção?** Redis e Postgres aqui são simulados ou
    locais; o relatório diz isso e a sobrecarga medida é dominada por eles.
33. **Como se testa o comportamento sob falha sem Docker?** Providers mock em processo e um chaos
    script com asserções. Ver `10`.
34. **O que falta testar com Redis real?** Concorrência de RPM (`test_100_concurrent_real_redis_exactly_50`,
    ignorada sem servidor) e a prova do orçamento. Pendente registado.
