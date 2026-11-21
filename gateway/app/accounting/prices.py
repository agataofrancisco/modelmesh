"""Tabela de preços versionada e cálculo de custo.

Cada preço é válido a partir de `effective_date`. Para um pedido com data `d`, usa-se a entrada
com a maior `effective_date <= d`. Sem preço, o pedido é recusado (`pricing_missing`): nunca se
assume custo zero.

Os valores monetários internos são inteiros em micro-USD (1 USD = 1_000_000) para que os
contadores de Redis sejam INCRBY exactos, sem erros de vírgula flutuante.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

MICRO = 1_000_000
SUPPORTED_CURRENCY = "USD"


@dataclass(frozen=True)
class PriceEntry:
    provider: str
    model: str
    input_per_mtok: Decimal  # USD por 1M tokens de entrada
    output_per_mtok: Decimal  # USD por 1M tokens de saída
    currency: str
    effective_date: date
    source: str


class PriceBook:
    def __init__(self, entries: list[PriceEntry] | None = None) -> None:
        self._series: dict[tuple[str, str], list[PriceEntry]] = {}
        for entry in entries or []:
            self.add(entry)

    def add(self, entry: PriceEntry) -> None:
        key = (entry.provider, entry.model)
        series = self._series.setdefault(key, [])
        series.append(entry)
        series.sort(key=lambda e: e.effective_date)

    def price_for(self, provider: str, model: str, on: date) -> PriceEntry | None:
        series = self._series.get((provider, model))
        if not series:
            return None
        dates = [e.effective_date for e in series]
        index = bisect_right(dates, on) - 1
        if index < 0:
            return None
        return series[index]

    def __len__(self) -> int:
        return sum(len(s) for s in self._series.values())


def parse_price_row(row: dict[str, Any]) -> PriceEntry:
    """Valida uma linha do YAML de preços. Levanta ValueError com mensagem legível."""
    required = (
        "provider",
        "model",
        "input_per_mtok",
        "output_per_mtok",
        "effective_date",
        "source",
    )
    missing = [k for k in required if k not in row]
    if missing:
        raise ValueError(f"preço sem campos obrigatórios: {missing}")
    currency = str(row.get("currency", SUPPORTED_CURRENCY))
    if currency != SUPPORTED_CURRENCY:
        raise ValueError(f"moeda não suportada no orçamento: {currency}")
    try:
        input_price = Decimal(str(row["input_per_mtok"]))
        output_price = Decimal(str(row["output_per_mtok"]))
    except ArithmeticError as exc:
        raise ValueError("preço não numérico") from exc
    if input_price < 0 or output_price < 0:
        raise ValueError("preços não podem ser negativos")
    effective = row["effective_date"]
    if isinstance(effective, str):
        effective = date.fromisoformat(effective)
    if not isinstance(effective, date):
        raise ValueError("effective_date inválida")
    return PriceEntry(
        provider=str(row["provider"]),
        model=str(row["model"]),
        input_per_mtok=input_price,
        output_per_mtok=output_price,
        currency=currency,
        effective_date=effective,
        source=str(row["source"]),
    )


def cost_micro(
    price: PriceEntry, tokens_in: int, tokens_out: int, *, rounding: str = "ceil"
) -> int:
    """Custo em micro-USD. Arredondamento para cima por defeito: o orçamento é conservador."""
    usd = (
        Decimal(tokens_in) * price.input_per_mtok + Decimal(tokens_out) * price.output_per_mtok
    ) / Decimal(1_000_000)
    micro = usd * MICRO
    if rounding == "ceil":
        return int(micro.to_integral_value(rounding=ROUND_CEILING))
    return int(micro.to_integral_value())


def micro_to_usd(micro: int) -> Decimal:
    return (Decimal(micro) / Decimal(MICRO)).quantize(Decimal("0.000001"))


def budget_usd_to_micro(usd: Decimal | float | int | str) -> int:
    """Limites de orçamento arredondam para BAIXO: nunca se concede mais do que o configurado."""
    value = Decimal(str(usd)) * MICRO
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def estimate_tokens(text: str) -> int:
    """Aproximação: ~4 caracteres por token. O erro é medido e documentado no learn 08."""
    return max(1, math.ceil(len(text) / 4))
