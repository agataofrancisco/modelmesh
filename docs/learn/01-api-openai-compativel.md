# 01 · API compatível com OpenAI

## O problema

As aplicações internas já usam o SDK oficial da OpenAI. Mudar cada uma para uma API nova custa
semanas. A solução é falar o mesmo protocolo: só muda o `base_url` e a chave.

## O que entra e o que sai

Entra o formato de pedido da OpenAI. Os campos suportados são `model`, `messages`, `temperature`,
`max_tokens`, `response_format` (definidos em `gateway/app/api/schemas.py:ChatCompletionRequest`).
Campos desconhecidos são ignorados e não são reenviados ao provider.

Saída real de um erro de política (modelo fora da lista da equipa):

```json
{"error":{"message":"modelo não permitido para esta equipa","type":"permission_error","param":null,"code":"model_not_allowed","request_id":"req_9290552c92c743789ab549565b11db85"}}
```

Saída real de um corpo inválido (`messages` vazio), antes de qualquer contacto com providers:

```json
{"error":{"message":"messages: List should have at least 1 item after validation, not 0","type":"invalid_request_error","param":null,"code":"invalid_request","request_id":"req_197c698e2020450081a5485356d23378"}}
```

Os campos `type`, `param`, `code`, `message` e `request_id` seguem o formato de erro da OpenAI.
O `code` é estável e vem do catálogo em `gateway/app/errors.py:ERROR_CATALOG`.

## Como funciona por dentro

- Validação em duas camadas: tamanho do corpo e JSON (`gateway/app/api/inference.py`), depois o
  schema Pydantic. Um erro de schema devolve `400 invalid_request` (não o `422` do FastAPI).
- `stream: true` devolve `400 streaming_not_supported`. O streaming fica para a fase 2.
- `max_tokens` acima do permitido pela política devolve `400 max_tokens_exceeded` antes do provider.
- O gateway acrescenta `max_tokens` quando o cliente não o envia, para limitar a reserva.

## Porquê esta escolha

Compatibilidade com o SDK é o critério de adoção. Validar antes de contactar o provider protege o
orçamento e evita enviar pedidos que o provider recusaria de qualquer forma.

## Alternativas

- Uma API própria (mais limpa, mas exige migração de todas as aplicações).
- Aceitar todos os campos e reenviar tudo: arrisca fugas de parâmetros e custos inesperados.

## Como falha

- Corpo acima de `MODELMESH_MAX_BODY_BYTES`: `413 body_too_large`.
- Sem `messages` com conteúdo: `400`. Teste: `test_invalid_body_is_400_openai_format`.
- SDK oficial a apontar ao gateway com servidores HTTP reais:
  `tests/integration/test_openai_sdk.py::test_official_openai_sdk_against_gateway`, que passa.
  O teste imprime a resposta do SDK em formato `ChatCompletion` com `usage`.

## Perguntas de entrevista

1. **Porque é que o `400` do schema não é o `422` por defeito do FastAPI?** A API da OpenAI
   devolve `400` para pedidos mal formados. O SDK trata `422` de forma diferente, por isso o gateway
   normaliza para o mesmo contrato.
2. **Porque se ignoram campos desconhecidos em vez de os rejeitar?** Compatibilidade: o SDK pode
   enviar campos novos. Rejeitar quebraria clientes. O risco é aceitável porque nada extra é
   reenviado ao provider.
3. **O que acontece a `stream: true`?** Recusado com `400` explícito. Não é silenciosamente
   convertido, porque o cliente esperaria SSE.
