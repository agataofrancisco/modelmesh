# Spec Delta

## Purpose

Saber exactamente quanto custa cada pedido, com preços versionados e auditáveis, e registar o uso sem guardar conteúdo privado.

## ADDED Requirements

### Requirement: Tabela de preços versionada
Os preços SHALL ser configurados por `(provider, modelo)` com preço por milhão de tokens de entrada e de saída, moeda, `effective_date` e fonte. O custo de um pedido MUST usar o preço em vigor na data do pedido.

#### Scenario: Mudança de preço
- **WHEN** é adicionado um preço novo com `effective_date` de amanhã
- **THEN** os pedidos de hoje continuam a usar o preço anterior

#### Scenario: Modelo sem preço
- **WHEN** um modelo permitido não tem preço configurado
- **THEN** o gateway recusa o pedido com `code: "pricing_missing"` em vez de assumir custo zero

### Requirement: Registo de uso
Cada pedido SHALL gerar um registo com equipa, chave (prefixo), modelo pedido, modelo servido, caminho de fallback, tokens de entrada e saída, custo estimado e real, latência, estado e `trace_id`.

#### Scenario: Pedido com fallback
- **WHEN** um pedido é servido por B depois de falhar em A
- **THEN** o registo mostra `fallback_path: ["A","B"]` e o custo apenas de B, salvo se A tiver cobrado tokens

### Requirement: Redacção de conteúdo
O registo de uso e os logs NÃO SHALL conter o conteúdo das mensagens nem as respostas, a não ser que uma flag de debug por equipa o active explicitamente, e mesmo assim com redacção de padrões sensíveis.

#### Scenario: Log normal
- **WHEN** um pedido contém um email e um número de telefone
- **THEN** nenhum dos dois aparece nos logs nem no registo de uso

### Requirement: Consulta de uso
`GET /admin/usage` SHALL devolver o uso agregado por equipa, chave, modelo e período, com filtros.

#### Scenario: Uso por equipa
- **WHEN** um admin pede o uso da equipa `dados` nos últimos 7 dias
- **THEN** recebe tokens, custo e número de pedidos por modelo
