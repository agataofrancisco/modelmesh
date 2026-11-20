# Spec Delta

## Purpose

Escolher para cada pedido o modelo com menor custo esperado por tarefa resolvida que cumpra as restrições de qualidade, latência e sensibilidade, e explicar porquê.

## ADDED Requirements

### Requirement: Decisão explicável sem execução
`POST /route` SHALL receber a tarefa (`task_type`, tamanho estimado, requisitos de JSON/ferramentas, SLA de latência, sensibilidade, tecto de custo) e devolver o modelo escolhido, os candidatos considerados, os excluídos com motivo e o custo esperado, sem chamar nenhum provider.

#### Scenario: Extracção JSON simples
- **WHEN** chega uma tarefa `json_extraction` curta com tecto de 0,002 USD
- **THEN** a resposta escolhe um modelo com suporte a JSON mode e explica os motivos de exclusão dos restantes (por exemplo `no_json_mode`, `over_cost_ceiling`)

#### Scenario: Nenhum modelo cumpre as restrições
- **WHEN** nenhum modelo do catálogo cumpre o SLA e o tecto de custo ao mesmo tempo
- **THEN** a resposta é `422` com `code: "no_eligible_model"` e as restrições em conflito

### Requirement: Restrições de sensibilidade
Pedidos marcados como sensíveis MUST ser encaminhados apenas para providers autorizados para dados sensíveis na política da equipa, independentemente do custo.

#### Scenario: Dados sensíveis
- **WHEN** um pedido traz `sensitivity: "high"`
- **THEN** só são considerados modelos de providers com `allow_sensitive: true`

### Requirement: Escalonamento com validação
`POST /execute` SHALL executar o modelo escolhido através do gateway e, quando a validação programática da tarefa (schema, asserts) falhar e a política o permitir, MUST escalar para o próximo modelo mais forte. O custo de todas as tentativas MUST ser registado e contar para o orçamento.

#### Scenario: JSON inválido no modelo barato
- **WHEN** o modelo barato devolve JSON que não valida o schema
- **THEN** o pedido é repetido no modelo seguinte e o registo mostra as duas tentativas e o custo total

### Requirement: Contabilidade completa do custo
O custo de uma tarefa MUST incluir retries, escalonamentos, reasoning tokens quando reportados e o desconto de prompt caching quando reportado. Os valores ausentes MUST ser marcados como estimados.

#### Scenario: Reasoning tokens reportados
- **WHEN** o provider reporta reasoning tokens
- **THEN** são incluídos no custo da tarefa ao preço correspondente

### Requirement: Interruptor do autopilot
Um admin SHALL poder desligar o autopilot por equipa. Desligado, o routing volta à política fixa do gateway.

#### Scenario: Autopilot desligado
- **WHEN** um admin desliga o autopilot da equipa `marketing`
- **THEN** os pedidos seguintes dessa equipa usam a cadeia fixa e o motivo registado é `autopilot_disabled`
