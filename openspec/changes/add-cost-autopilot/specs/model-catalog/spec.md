# Spec Delta

## Purpose

Manter um catálogo de modelos com capacidades verificadas e preços versionados, que a política de custo usa como fonte única de verdade.

## ADDED Requirements

### Requirement: Catálogo por configuração
O catálogo SHALL ser carregado de configuração versionada com, por modelo: provider, contexto máximo, suporte a JSON mode, suporte a ferramentas, latência típica observada e permissão para dados sensíveis. Os preços MUST vir da tabela de preços versionada do gateway.

#### Scenario: Modelo sem preço
- **WHEN** o catálogo contém um modelo sem preço em vigor
- **THEN** esse modelo é marcado como `ineligible: pricing_missing` e nunca é escolhido

### Requirement: Validação de capacidades no arranque
No arranque, e a pedido do admin, o sistema SHALL verificar as capacidades declaradas com uma sonda barata por modelo (em modo real) ou contra o mock (em demo) e MUST marcar as divergências.

#### Scenario: Capacidade declarada falsa
- **WHEN** um modelo declarado com JSON mode falha a sonda de JSON
- **THEN** o modelo fica com `capability_mismatch: json_mode` e é excluído de tarefas que exigem JSON

### Requirement: Histórico de sucesso
O catálogo SHALL manter por `(modelo, task_type)` a taxa de sucesso observada e a latência p95, actualizadas a partir do registo de uso, e expô-las à política.

#### Scenario: Degradação observada
- **WHEN** a taxa de sucesso de um modelo para `multi_step_reasoning` desce abaixo do limiar
- **THEN** a política deixa de o escolher para esse tipo e regista `low_success_rate`
