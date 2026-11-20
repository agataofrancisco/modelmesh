# Tasks

## 1. Catálogo

- [ ] 1.1 Implementar o catálogo por configuração ligado à tabela de preços e a exclusão `pricing_missing`; verificar com testes
- [ ] 1.2 Implementar as sondas de capacidade (mock/real) e `capability_mismatch`; verificar com teste de JSON mode falso
- [ ] 1.3 Implementar o histórico por `(modelo, task_type)` com prior Beta a partir do registo de uso; verificar com teste de actualização e de `low_success_rate`

## 2. Política e execução

- [ ] 2.1 Implementar `decide()` puro (filtros, custo esperado, alvo de qualidade, SLA) e `POST /route` com explicação; verificar com testes de escolha, exclusões e `no_eligible_model`
- [ ] 2.2 Implementar validadores por tipo de tarefa e `POST /execute` com escalonamento e contabilidade completa (retries, reasoning tokens, caching); verificar com teste de JSON inválido → escalonamento e custo das 2 tentativas
- [ ] 2.3 Implementar o interruptor por equipa e a restrição de sensibilidade; verificar com testes
- [ ] 2.4 Escrever `docs/learn/12-custo-por-tarefa-resolvida.md`, `13-cascata-e-escalonamento.md` e `14-priors-beta-e-historico.md`; verificar os exemplos numéricos com testes

## 3. Cache

- [ ] 3.1 Implementar a cache com elegibilidade, isolamento, TTL e cabeçalho de hit; verificar com testes de temperatura > 0, equipas diferentes e hit com custo 0
- [ ] 3.2 Escrever `docs/learn/15-cache-segura.md`; verificar que os riscos têm testes

## 4. Benchmark e contrafactual

- [ ] 4.1 Criar o dataset de ≥100 tarefas (4 tipos) com critérios de correcção e validador; verificar com o validador
- [ ] 4.2 Implementar o runner das 3 políticas com as métricas da spec e o juiz opcional calibrado; verificar que gera o relatório em mock marcado `simulated`
- [ ] 4.3 Implementar a simulação contrafactual sobre logs, com `source` e `unknown` quando não há observação; verificar com teste
- [ ] 4.4 Correr o benchmark em mock e gravar `reports/ablation.md`; verificar que os campos de portefólio estão como `TODO: medir`
- [ ] 4.5 Escrever `docs/learn/16-contrafactual-e-ablacao.md`; verificar que os números citados vêm do relatório

## 5. Painel e integração

- [ ] 5.1 Acrescentar ao painel o custo por equipa/provider/tarefa, o gráfico custo vs qualidade, a distribuição de routing, os motivos e o interruptor; verificar no browser
- [ ] 5.2 Testes de integração: orçamento sob concorrência com escalonamento, preço desactualizado, model mismatch, tokens não reportados, multi-tenant e provider indisponível; verificar que passam
- [ ] 5.3 Actualizar o README, `docs/decisions.md` (o que o OpenRouter/LiteLLM já fazem vs a contribuição) e as perguntas de entrevista; verificar os comandos

## Workflow follow-up

- Execução real do benchmark com `--max-usd` para obter os números do portefólio.
- Arquivar a change após revisão.
