# Spec Delta

## Purpose

Impedir que uma equipa ou chave exceda o seu ritmo ou o seu orçamento, mesmo sob alta concorrência e quando os providers não reportam uso.

## ADDED Requirements

### Requirement: Rate limit atómico
O gateway SHALL aplicar limites de pedidos por minuto, tokens por minuto (estimados à entrada) e pedidos simultâneos por chave e por equipa. A verificação e o incremento MUST ser atómicos.

#### Scenario: 100 pedidos concorrentes
- **WHEN** 100 pedidos simultâneos chegam a uma chave com limite de 50 RPM
- **THEN** exactamente 50 são aceites e 50 recebem `429` com `code: "rate_limited"` e `Retry-After`

#### Scenario: Limite de concorrência
- **WHEN** uma chave com concorrência máxima 5 tem 5 pedidos em curso
- **THEN** o sexto é rejeitado e o contador baixa quando um pedido termina, mesmo com erro

### Requirement: Reserva de orçamento antes do pedido
Antes de contactar o provider, o gateway MUST reservar atomicamente o custo máximo estimado do pedido contra os orçamentos da chave e da equipa. Se a reserva exceder algum orçamento, o pedido MUST ser rejeitado.

#### Scenario: Orçamento de 1 USD sob concorrência
- **WHEN** 200 pedidos simultâneos, com preços fictícios nos mocks, competem por um orçamento de 1 USD
- **THEN** o gasto reconciliado final não excede 1 USD e os pedidos rejeitados recebem `402` com `code: "budget_exceeded"`

### Requirement: Reconciliação após uso real
Depois da resposta, o gateway SHALL substituir a reserva pelo custo real calculado a partir do `usage`. Se o provider não reportar `usage`, MUST manter o custo estimado e marcar o registo como `usage_estimated`.

#### Scenario: Usage ausente
- **WHEN** o provider responde sem `usage`
- **THEN** o registo de uso fica com o custo estimado e `usage_estimated: true`

#### Scenario: Pedido falhado
- **WHEN** todos os hops falham sem consumir tokens
- **THEN** a reserva é libertada

### Requirement: Reservas órfãs
Reservas de pedidos cujo processo terminou abruptamente MUST expirar após um TTL e ser libertadas ou reconciliadas, sem permitir gasto acima do orçamento.

#### Scenario: Crash a meio do pedido
- **WHEN** o processo do gateway termina depois de reservar e antes de reconciliar
- **THEN** após o TTL a reserva é libertada e o evento `orphan_reservation_released` é registado
