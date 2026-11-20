# Spec Delta

## Purpose

Provar experimentalmente se a política híbrida reduz o custo por tarefa resolvida sem degradação inaceitável, comparando-a com baselines simples sobre o mesmo dataset.

## ADDED Requirements

### Requirement: Dataset de tarefas
O projecto SHALL incluir pelo menos 100 tarefas sintéticas curadas em 4 tipos (classificação simples, extracção JSON, raciocínio multi-step, perguntas sobre documentação), cada uma com um label humano ou um assert programático.

#### Scenario: Validação do dataset
- **WHEN** o runner arranca
- **THEN** confirma que cada tarefa tem tipo e critério de correcção e falha em caso contrário

### Requirement: Comparação de políticas
O runner SHALL executar `always_expensive`, `always_cheap` e `hybrid` sobre exactamente as mesmas tarefas e medir a taxa de tarefas resolvidas, exact match/field F1 quando aplicável, custo por tarefa resolvida, latência p50/p95 e número de retries e escalonamentos.

#### Scenario: Relatório de ablação
- **WHEN** a comparação termina
- **THEN** `reports/ablation.md` contém uma tabela das 3 políticas por tipo de tarefa, com data, commit, modelos e modo (mock ou real)

### Requirement: LLM judge só calibrado
Se for usado um juiz LLM, o sistema MUST calibrá-lo primeiro contra uma amostra com labels humanos e reportar a concordância. Sem calibração, o juiz NÃO SHALL contar para as métricas principais.

#### Scenario: Juiz não calibrado
- **WHEN** o juiz é activado sem amostra calibrada
- **THEN** as suas pontuações aparecem apenas como sinal secundário, marcadas `uncalibrated`

### Requirement: Simulação contrafactual offline
O sistema SHALL estimar, a partir de logs anonimizados ou sintéticos explicitamente marcados, o custo e a qualidade que outra política teria tido, sem executar pedidos novos, e MUST indicar as suposições usadas.

#### Scenario: Logs sintéticos
- **WHEN** a simulação corre sobre logs sintéticos
- **THEN** o relatório indica `source: synthetic` e não apresenta o resultado como poupança real

### Requirement: Nenhuma poupança sem logs reais
Nenhuma percentagem de redução de custo SHALL ser publicada sem os logs de execução que a produziram.

#### Scenario: Benchmark em mock
- **WHEN** o benchmark corre apenas contra mocks
- **THEN** o relatório marca as diferenças de custo como `simulated` e mantém as métricas de portefólio como `TODO: medir`
