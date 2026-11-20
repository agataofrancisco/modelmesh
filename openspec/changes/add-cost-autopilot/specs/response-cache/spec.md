# Spec Delta

## Purpose

Poupar custo e latência em pedidos repetidos sem nunca servir respostas a quem não as deve ver nem respostas que deviam variar.

## ADDED Requirements

### Requirement: Elegibilidade estrita
Só pedidos com `temperature` 0, sem ferramentas, sem sensibilidade alta e com `cache: true` explícito SHALL ser elegíveis para cache. Todos os outros MUST ignorar a cache.

#### Scenario: Pedido com temperatura alta
- **WHEN** um pedido com `temperature: 0.7` é repetido
- **THEN** é sempre enviado ao provider e não é guardado

### Requirement: Isolamento por tenant
A chave de cache MUST incluir o tenant, a equipa, o modelo, os parâmetros e o hash do conteúdo. Uma resposta em cache NÃO SHALL ser servida a outro tenant ou equipa.

#### Scenario: Mesmo pedido em equipas diferentes
- **WHEN** as equipas `suporte` e `dados` enviam o mesmo pedido elegível
- **THEN** cada uma recebe a sua própria resposta e não há hit cruzado

### Requirement: Transparência e expiração
As respostas servidas da cache SHALL ter o cabeçalho `x-modelmesh-cache: hit`, custo zero no registo de uso e um TTL configurável.

#### Scenario: Hit de cache
- **WHEN** um pedido elegível é repetido dentro do TTL
- **THEN** a resposta vem da cache, com `x-modelmesh-cache: hit` e custo 0 registado
