"""Deterministic forecast-horizon extraction from the question text.

"What will revenue be over the next 3 months?" -> ``Horizon(periods=3,
grain="month", anchor=...)``. This is a fixed rule table, not a model call,
so it works with no model service available and is fully testable. The horizon is
always anchored on the last *complete* period the caller supplies
(V2-DATA-2); the parser never decides the anchor itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from contracts.models import MetricTimeGrain
from contracts.v2 import Horizon

_NUMBER_WORDS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "couple of": 2, "um": 1, "uma": 1, "dois": 2, "duas": 2, "tres": 3, "três": 3,
    "quatro": 4, "cinco": 5, "seis": 6, "doze": 12,
}
_UNITS: dict[str, tuple[str, int]] = {
    "day": ("day", 1), "days": ("day", 1), "dia": ("day", 1), "dias": ("day", 1),
    "week": ("week", 1), "weeks": ("week", 1), "semana": ("week", 1), "semanas": ("week", 1),
    "month": ("month", 1), "months": ("month", 1), "mes": ("month", 1), "mês": ("month", 1), "meses": ("month", 1),
    "quarter": ("month", 3), "quarters": ("month", 3), "trimestre": ("month", 3), "trimestres": ("month", 3),
    "year": ("month", 12), "years": ("month", 12), "ano": ("month", 12), "anos": ("month", 12),
}
_MONTHS = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan", "janeiro"), ("february", "feb", "fevereiro"), ("march", "mar", "março", "marco"),
            ("april", "apr", "abril"), ("may", "maio"), ("june", "jun", "junho"), ("july", "jul", "julho"),
            ("august", "aug", "agosto"), ("september", "sep", "sept", "setembro"), ("october", "oct", "outubro"),
            ("november", "nov", "novembro"), ("december", "dec", "dezembro"),
        ),
        start=1,
    )
    for name in names
}
_NUMBER = r"(\d{1,3}|" + "|".join(sorted((re.escape(word) for word in _NUMBER_WORDS), key=len, reverse=True)) + r")"
_UNIT = r"(" + "|".join(sorted((re.escape(unit) for unit in _UNITS), key=len, reverse=True)) + r")"

_COUNTED = (
    re.compile(rf"\b(?:next|coming|upcoming|following|pr[oó]xim[oa]s?)\s+{_NUMBER}\s+{_UNIT}\b"),
    re.compile(rf"\b(?:over|for|in|within|during|across)\s+(?:the\s+)?(?:next\s+)?{_NUMBER}\s+{_UNIT}\b"),
    re.compile(rf"\b{_NUMBER}\s+{_UNIT}\s+(?:ahead|out|from now|forward)\b"),
    re.compile(rf"\b(?:nos|nas)\s+pr[oó]xim[oa]s\s+{_NUMBER}\s+{_UNIT}\b"),
)
_SINGLE = re.compile(rf"\b(?:next|coming|following|pr[oó]xim[oa])\s+{_UNIT}\b")
_YEAR_END = re.compile(r"\b(?:rest of (?:the |this )?year|end of (?:the |this )?year|year[- ]end|fim do ano)\b")
_UNTIL = re.compile(
    r"\b(?:until|till|through|thru|by|to|before|at|for|in|até)\s+(?:the\s+)?(?:end\s+of\s+)?"
    r"([a-zçã]+|q[1-4])\s*(?:of\s+)?(\d{4})\b"
)


@dataclass(frozen=True)
class HorizonParse:
    horizon: Horizon | None
    phrase: str | None
    reason: str


def _count(token: str) -> int:
    token = token.strip()
    return int(token) if token.isdigit() else _NUMBER_WORDS[token]


def _months_between(anchor: date, year: int, month: int) -> int:
    return (year - anchor.year) * 12 + (month - anchor.month)


def _anchor_date(anchor: str) -> date:
    parts = anchor.strip()[:10].split("-")
    return date(int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) > 2 else 1)


def _convert(periods: int, unit_grain: str, factor: int, grain: MetricTimeGrain) -> tuple[int, MetricTimeGrain]:
    if unit_grain == grain or (unit_grain == "month" and grain == "month"):
        return periods * factor, grain
    if unit_grain == "month":
        # A month-based horizon asked of a finer series is kept in months.
        return periods * factor, "month"
    return periods * factor, unit_grain  # type: ignore[return-value]


def extract_horizon(question: str, *, anchor: str, grain: MetricTimeGrain = "month") -> HorizonParse:
    """Return the horizon the question asks for, or ``None`` with a reason."""

    text = " ".join(question.lower().split())
    base = _anchor_date(anchor)
    for pattern in _COUNTED:
        match = pattern.search(text)
        if match:
            unit_grain, factor = _UNITS[match.group(2)]
            periods, out_grain = _convert(_count(match.group(1)), unit_grain, factor, grain)
            if periods >= 1:
                return HorizonParse(Horizon(periods=periods, grain=out_grain, anchor=anchor), match.group(0), "counted horizon")
    match = _SINGLE.search(text)
    if match:
        unit_grain, factor = _UNITS[match.group(1)]
        periods, out_grain = _convert(1, unit_grain, factor, grain)
        return HorizonParse(Horizon(periods=periods, grain=out_grain, anchor=anchor), match.group(0), "single next period")
    match = _YEAR_END.search(text)
    if match:
        periods = _months_between(base, base.year, 12)
        if periods >= 1:
            return HorizonParse(Horizon(periods=periods, grain="month", anchor=anchor), match.group(0), "to the end of the anchor year")
        return HorizonParse(None, match.group(0), "the anchor is already the last month of its year")
    match = _UNTIL.search(text)
    if match:
        word, year = match.group(1), int(match.group(2))
        if word.startswith("q") and word[1:].isdigit():
            month = int(word[1:]) * 3
        elif word in _MONTHS:
            month = _MONTHS[word]
        elif word in {"end", "fim"}:
            month = 12
        else:
            month = None
        if month is not None:
            periods = _months_between(base, year, month)
            if periods >= 1:
                return HorizonParse(Horizon(periods=periods, grain="month", anchor=anchor), match.group(0), "until a named period")
            return HorizonParse(None, match.group(0), "the named period is not after the anchor")
    return HorizonParse(None, None, "no forecast horizon was stated in the question")


__all__ = ["HorizonParse", "extract_horizon"]
