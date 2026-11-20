# Proposal

## Why

O gateway (`bootstrap-modelmesh-gateway`) já controla quem gasta e quanto, mas não decide **qual o modelo mais barato que ainda resolve bem cada tarefa**. Usar sempre o modelo caro desperdiça dinheiro. Usar sempre o barato degrada a qualidade e pode até sair mais caro por causa dos retries e das falhas. O CostPilot acrescenta ao ModelMesh uma política de routing calibrada com um dataset e com restrições de qualidade mensuráveis. Mede o **custo por tarefa resolvida**, e não o preço por token. O OpenRouter e o LiteLLM já fazem routing; a contribuição aqui é a política calibrada e a prova experimental.

## What Changes

- Novo módulo `costpilot` no ModelMesh com `POST /route` (decisão explicável sem executar) e `POST /execute` (executa via o gateway com o hard-limit de orçamento existente).
- Catálogo de modelos com capacidades (JSON mode, tool use, contexto máximo) validadas no arranque e preços vindos da tabela versionada do gateway.
- Política determinística inicial baseada em `task_type`, tamanho do input, requisitos de JSON/ferramentas, SLA, sensibilidade, histórico de sucesso e tecto de custo. Um classificador ML é opcional e só entra depois de avaliado.
- Escalonamento: tentar um modelo barato e subir para um mais forte quando uma validação programática falha. O custo de todas as tentativas é contado.
- Cache de respostas apenas para pedidos seguros e determinísticos, isolada por tenant.
- Simulação contrafactual offline sobre logs anonimizados ou sintéticos, sempre marcados como tal.
- Benchmark com 100 ou mais tarefas em 4 tipos, comparando `always_expensive`, `always_cheap` e a política híbrida. Relatório `reports/ablation.md` só com valores medidos.
- Painel: custo por equipa/provider/tarefa, gráfico custo vs qualidade, distribuição de routing, motivos das decisões e um interruptor para desligar o autopilot.

## Capabilities

### New Capabilities
- `cost-aware-routing`: decisão de modelo por restrições e custo, explicação, escalonamento e interruptor.
- `model-catalog`: capacidades dos modelos validadas e ligação aos preços versionados.
- `response-cache`: cache segura, isolada por tenant e com regras de elegibilidade.
- `cost-quality-benchmark`: dataset de tarefas, baselines, simulação contrafactual e relatório de ablação.

### Modified Capabilities
<!-- Nenhuma alteração de requisitos às capabilities do gateway: o CostPilot usa routing-policy, rate-limits-and-budgets e usage-accounting tal como estão. -->

## Impact

- **Código**: `gateway/app/costpilot/`, `bench/costpilot/`, `reports/` e novas vistas no painel.
- **Dependências**: nenhuma obrigatória além das do gateway. scikit-learn só se o classificador opcional for avaliado.
- **Dependência de change**: requer `bootstrap-modelmesh-gateway` implementada (preços, orçamentos, adaptadores, registo de uso).
- **Fora de âmbito**: routing semântico com embeddings, e cache semântica (por similaridade).
