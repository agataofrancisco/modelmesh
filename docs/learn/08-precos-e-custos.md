# 08 · Preços versionados e cálculo de custo

## O problema

Um preço mudou amanhã. Os pedidos de hoje têm de continuar a ser cobrados ao preço de hoje, e um
modelo sem preço não pode ser tratado como grátis.

## O que entra e o que sai

Entra uma linha de preço: `provider`, `model`, `input_per_mtok`, `output_per_mtok`, `currency`,
`effective_date`, `source`. Sai um custo em micro-USD (inteiro). Modelo sem preço para a data do
pedido: `503 pricing_missing`, sem chamar provider.

## Como funciona por dentro

- `gateway/app/accounting/prices.py:PriceBook.price_for` escolhe a linha com a maior
  `effective_date <= data do pedido` (`bisect_right`).
- `cost_micro` calcula `(tokens_in * preço_in + tokens_out * preço_out) / 1e6` e converte para
  micro-USD com arredondamento para cima.
- `parse_price_row` rejeita moedas que não sejam USD, preços negativos e campos em falta. O seed
  carrega `migrations/seed/prices.yaml` (valores fictícios, marcados como tal).

Exemplo trabalhado, verificado pelo teste (`test_cost_worked_example_is_exact`): 1000 tokens de
entrada a 1 USD/MTok mais 500 de saída a 2 USD/MTok = 0,002 USD = **2000 micro-USD**.

## Porquê esta escolha

- **Linhas com data de vigência**: o histórico fica auditável, e uma alteração futura não reescreve
  o passado.
- **Micro-USD inteiros**: `INCRBY` não tem erros de vírgula flutuante. Somar mil pedidos continua
  exacto.
- **Preço ausente recusa o pedido**: assumir custo zero faria o orçamento parecer intacto.

## Alternativas

- Preço em `float`: simples, mas acumula erro nos contadores.
- Preço em constantes no código: não auditável e exige deploy para mudar.

## Como falha

- Mudança de preço só vale a partir da data: `test_price_uses_latest_effective_date_not_after_request_date`.
- Modelo sem preço: `test_missing_price_refuses_with_pricing_missing` (provider nunca chamado).
- Usage ausente: o custo é a estimativa do hop servido e `usage_estimated: true`
  (`test_missing_usage_marked_as_estimated`).

**Erro da estimativa de tokens**: `estimate_tokens` usa ~4 caracteres por token, uma aproximação.
Não foi medida contra um tokenizador real neste projeto; fica como `TODO: medir` com um tokenizador
do provider real.

## Perguntas de entrevista

1. **Porque micro-USD e não decimal?** Contadores atómicos em Redis são inteiros. A precisão do
   `Decimal` é mantida no Postgres.
2. **Como se muda um preço sem reescrever o histórico?** Inserindo uma linha nova com outra
   `effective_date`. Nunca se edita a antiga.
3. **Porque arredondar o custo para cima?** Sob dúvida, o orçamento deve ser mais conservador.
