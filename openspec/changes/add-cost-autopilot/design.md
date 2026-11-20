# Design

## Context

Esta change é construída sobre a `bootstrap-modelmesh-gateway` (adaptadores, preços, orçamentos e registo de uso já existem). Motivação: ver `proposal.md`. Requisitos: ver `specs/`.

## Goals / Non-Goals

**Goals:**
- Uma política simples, determinística e explicável, que bate as baselines **com medição**.
- A métrica central é o custo por tarefa resolvida (`custo_total / tarefas_correctas`).

**Non-Goals:**
- Routing por embeddings ou modelos de preferência aprendidos (como o RouteLLM). Ficam citados como alternativa.
- A cache semântica.

## Decisions

### D1 — Política como função pura com pontuação
`decide(task, catalog, history, constraints) -> Decision`:
1. **Filtro duro:** capacidades, sensibilidade, contexto, preço em vigor e circuito aberto.
2. **Custo esperado** por candidato: `E[custo] = custo_tentativa + (1 - p_sucesso) * E[custo_escalonamento]`, com `p_sucesso` do histórico por `(modelo, task_type)` e um prior quando não há dados.
3. **Restrição de qualidade:** `p_sucesso >= alvo[task_type]`.
4. Escolher o menor `E[custo]` que cumpre o SLA de latência p95.

É uma função pura, por isso é testável com fixtures e reutilizada pela simulação contrafactual.
- *Alternativa:* classificador ML (complexidade → modelo). Opcional e só depois de existirem dados. Exige uma avaliação holdout antes de ser activado.

### D2 — Escalonamento em cascata
É o padrão "cascade" (citado na literatura como FrugalGPT). A cadeia ordenada por custo é percorrida até a validação programática passar ou o tecto ser atingido. A validação é por tipo: schema Pydantic para JSON, label exacto para classificação, asserts para raciocínio, e citação/referência para perguntas de documentação.

### D3 — Prior de sucesso
Beta(α, β) por `(modelo, task_type)`, iniciado com um prior fraco, que dá `p = α/(α+β)`. É actualizado a partir do registo de uso. Isto evita confiar em 3 amostras e é uma boa pergunta de entrevista sobre exploração vs aproveitamento (explore/exploit).

### D4 — Cache
Redis com a chave `sha256(tenant|team|model|params_canonicos|messages_canonicas)` e um TTL. A elegibilidade é verificada antes de ler. Nunca se guardam respostas a pedidos sensíveis.

### D5 — Contrafactual
Reaproveita `decide()` sobre os logs: para cada pedido registado, calcula o modelo que a política alternativa escolheria. Só estima resultado quando existe uma observação desse modelo para a mesma tarefa (dataset de benchmark). Caso contrário marca `unknown` e não extrapola.

### D6 — Benchmark
`bench/costpilot/tasks.jsonl` e um runner que chama `/execute` com cada política fixada. Em mock, os mocks têm perfis de qualidade por "modelo" (por exemplo, o barato falha 25% em multi-step), declarados no relatório como simulação. Em real, usa modelos configurados e o tecto `--max-usd`.

### D7 — Documentação pedagógica
`docs/learn/` acrescenta `12-custo-por-tarefa-resolvida`, `13-cascata-e-escalonamento`, `14-priors-beta-e-historico`, `15-cache-segura` e `16-contrafactual-e-ablacao`, e actualiza as perguntas de entrevista.

## Risks / Trade-offs

- [Os perfis de qualidade dos mocks determinam o resultado] → O resultado em mock serve só para validar a mecânica. As conclusões de portefólio exigem a execução real.
- [Poucos dados tornam o histórico enviesado] → Prior Beta e um mínimo de amostras antes de confiar.
- [O escalonamento aumenta a latência no pior caso] → Medido em p95 e limitado pelo SLA.
- [Uma cache mal configurada fuga dados] → Isolamento por chave e testes cross-tenant obrigatórios.

## Migration Plan

Activado por flag por equipa (por omissão desligado). Rollback: desligar a flag, e o gateway volta à política fixa.
