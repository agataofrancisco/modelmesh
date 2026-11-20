# Spec Delta

## Purpose

Provar com experiências reproduzíveis que o gateway se comporta correctamente quando os providers falham e medir o custo de latência que acrescenta.

## ADDED Requirements

### Requirement: Providers simulados controláveis
O projecto SHALL incluir os providers `mock_provider_a` e `mock_provider_b`, compatíveis com OpenAI, cujo comportamento (latência, timeout, 429, 5xx, JSON inválido, falta de `usage`, preço fictício) é configurável por pedido ou por perfil.

#### Scenario: Perfil de falha
- **WHEN** o mock A é configurado com 30% de 503
- **THEN** cerca de 30% das respostas de A são 503 numa amostra de 1000 pedidos com seed fixa

### Requirement: Cenários de chaos
Um script SHALL executar os cenários: A falha→B responde; ambos falham; tempestade de 429; provider lento; JSON inválido; usage ausente; Redis indisponível; orçamento de 1 USD sob 200 pedidos concorrentes. Cada cenário MUST ter uma asserção automática e falhar o processo se a asserção falhar.

#### Scenario: Zero bypass de orçamento
- **WHEN** o cenário de orçamento termina
- **THEN** a asserção confirma que o gasto reconciliado é menor ou igual ao orçamento

### Requirement: Benchmark de overhead
O projecto SHALL medir a latência p50/p95/p99 do cliente directamente ao mock e através do gateway, com o mesmo perfil de carga, e a latência com e sem fallback, e MUST publicar os resultados com hardware, data e commit.

#### Scenario: Relatório de overhead
- **WHEN** o benchmark termina
- **THEN** o relatório mostra o overhead do proxy em ms por percentil, com os parâmetros da carga

### Requirement: Honestidade
Os relatórios MUST indicar que os resultados foram obtidos com providers simulados e NÃO SHALL extrapolá-los para providers reais sem medição.

#### Scenario: Relatório de chaos
- **WHEN** o relatório é gerado
- **THEN** inclui `providers: mock` e as limitações conhecidas
