# Spec Delta

## Purpose

Decidir para que modelo e provider vai cada pedido e como recuperar de falhas, segundo uma política declarativa e explicável por equipa.

## ADDED Requirements

### Requirement: Política declarativa por equipa
Cada equipa SHALL ter uma política com modelos permitidos, mapeamento de classes (`cheap`, `balanced`, `critical`) para cadeias ordenadas de `(provider, modelo)` e limites de tokens. `PUT /admin/policies/{team}` MUST validar a política antes de a aplicar.

#### Scenario: Modelo não permitido
- **WHEN** a equipa `marketing` pede um modelo fora da sua lista
- **THEN** o gateway devolve `403` com `code: "model_not_allowed"`

#### Scenario: Política inválida
- **WHEN** um admin envia uma cadeia de fallback que referencia um provider inexistente
- **THEN** a política é rejeitada com `422` e a anterior mantém-se

### Requirement: Fallback limitado
Quando um hop falha com um erro elegível, o gateway SHALL tentar o hop seguinte da cadeia, até ao número máximo de hops configurado. Erros de cliente (4xx excepto 408/429) NÃO SHALL provocar fallback.

#### Scenario: Provider A falha, B responde
- **WHEN** o provider A devolve `503` e o B responde
- **THEN** o cliente recebe a resposta de B e o cabeçalho `x-modelmesh-fallback-path` mostra `A→B`

#### Scenario: Erro do cliente
- **WHEN** o provider A devolve `400` por um pedido inválido
- **THEN** o gateway devolve o erro sem tentar B

### Requirement: Retries com backoff
Erros transitórios (timeout, 429, 5xx) SHALL ser repetidos no mesmo hop até ao limite configurado, com backoff exponencial e jitter, respeitando `Retry-After` quando existir e o timeout total do pedido.

#### Scenario: 429 com Retry-After
- **WHEN** o provider devolve `429` com `Retry-After: 1`
- **THEN** o gateway espera pelo menos 1 segundo antes de repetir, ou passa ao hop seguinte se isso exceder o timeout total

### Requirement: Circuit breaker
Por cada `(provider, modelo)`, o gateway SHALL abrir o circuito quando a taxa de falhas numa janela excede o limiar, saltar esse hop durante o cooldown e testar com um pedido em estado half-open antes de fechar.

#### Scenario: Circuito aberto
- **WHEN** o provider A falhou acima do limiar na janela
- **THEN** os pedidos seguintes vão directamente para B sem tentar A até ao fim do cooldown

#### Scenario: Recuperação
- **WHEN** o cooldown termina e o pedido de teste a A tem sucesso
- **THEN** o circuito fecha e A volta a ser o primeiro hop

### Requirement: Timeout por hop
Cada hop MUST ter um timeout próprio e o pedido MUST ter um timeout total, e NÃO SHALL ultrapassar o timeout total em caso nenhum.

#### Scenario: Provider lento
- **WHEN** o provider A não responde dentro do timeout do hop
- **THEN** o gateway desiste de A, tenta B e regista `timeout` para A
