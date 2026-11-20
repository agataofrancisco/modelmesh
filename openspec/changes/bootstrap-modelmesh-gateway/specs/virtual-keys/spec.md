# Spec Delta

## Purpose

Gerir credenciais por equipa de forma segura: chaves de inferência mostradas uma única vez, guardadas como hash e revogáveis, separadas das credenciais de administração.

## ADDED Requirements

### Requirement: Emissão de chave mostrada uma vez
`POST /admin/keys` SHALL gerar uma chave aleatória com prefixo identificável e devolvê-la em claro **uma única vez**. O sistema MUST guardar apenas um hash e um prefixo curto para identificação.

#### Scenario: Criar chave
- **WHEN** um admin cria uma chave para a equipa `suporte`
- **THEN** a resposta contém a chave completa e consultas posteriores mostram só o prefixo, a equipa, a data e o estado

### Requirement: Escopo por equipa
Cada chave MUST pertencer a uma equipa e herdar a política, os limites e o orçamento dessa equipa, MAY ter limites próprios mais restritivos e NÃO SHALL dar acesso a dados de outras equipas.

#### Scenario: Limite da chave mais restrito
- **WHEN** a equipa tem 100 RPM e a chave tem 10 RPM
- **THEN** a chave é limitada a 10 RPM

### Requirement: Revogação imediata
Revogar uma chave MUST impedir novos pedidos com ela em segundos e não SHALL afectar outras chaves.

#### Scenario: Chave revogada
- **WHEN** um admin revoga uma chave e a seguir é usada
- **THEN** o gateway devolve `401` com `code: "invalid_api_key"`

### Requirement: Administração separada
Os endpoints `/admin/*` MUST exigir credenciais de administração distintas das chaves de inferência. Uma chave de inferência NÃO SHALL aceder à administração.

#### Scenario: Chave de inferência na administração
- **WHEN** uma chave virtual chama `POST /admin/teams`
- **THEN** o gateway devolve `403`
