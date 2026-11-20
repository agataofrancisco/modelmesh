# Spec Delta

## Purpose

Oferecer às aplicações internas um endpoint de chat completions compatível com a API da OpenAI, para que possam usar o gateway sem alterar o seu SDK.

## ADDED Requirements

### Requirement: Endpoint compatível
`POST /v1/chat/completions` SHALL aceitar o formato de pedido da API OpenAI (`model`, `messages`, `temperature`, `max_tokens`, `response_format`) e devolver o formato de resposta compatível, incluindo `usage`. O campo `model` MAY ser um modelo concreto ou um alias de classe (`cheap`, `balanced`, `critical`).

#### Scenario: Pedido com SDK oficial
- **WHEN** uma aplicação usa o SDK oficial da OpenAI com `base_url` do gateway e uma chave virtual
- **THEN** recebe uma resposta válida para o SDK, com `id`, `choices` e `usage`

#### Scenario: Alias de classe
- **WHEN** o pedido traz `model: "cheap"`
- **THEN** o gateway resolve o modelo concreto pela política da equipa e indica-o no cabeçalho `x-modelmesh-model`

### Requirement: Validação e limites de pedido
O gateway MUST rejeitar pedidos mal formados, com corpo acima do limite ou com `max_tokens` acima do permitido pela política, antes de contactar qualquer provider.

#### Scenario: Corpo inválido
- **WHEN** `messages` está vazio
- **THEN** o gateway devolve `400` em formato de erro OpenAI e não contacta o provider

### Requirement: Erros coerentes
Todas as falhas SHALL ser devolvidas no formato de erro OpenAI, com `type` e `code` estáveis (`invalid_api_key`, `model_not_allowed`, `rate_limited`, `budget_exceeded`, `upstream_unavailable`, `timeout`) e um `request_id`.

#### Scenario: Todos os providers falham
- **WHEN** todos os hops da cadeia de fallback falham
- **THEN** o gateway devolve `503` com `code: "upstream_unavailable"`, o `request_id` e a lista de hops tentados sem detalhes sensíveis

### Requirement: Sem proxy aberto
O endpoint de inferência MUST exigir uma chave virtual válida. Nenhuma chave de provider SHALL ser devolvida ou registada.

#### Scenario: Sem chave
- **WHEN** um pedido chega sem `Authorization`
- **THEN** o gateway devolve `401` e não contacta nenhum provider
