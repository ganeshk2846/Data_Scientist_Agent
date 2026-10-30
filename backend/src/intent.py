"""V2 intent and entity extraction (contracts.md section 3, RTE-2, IR-1..7).

Rules first, grounded on the semantic layer:

1. **Rules** - per-clause patterns for the eight intents. A compound question
   ("how does revenue trend look today and what will it be in 3 months?") is
   split into clauses and each clause contributes its own intent and span.
2. **Classifier** - a keyword bag over the same vocabulary, used to confirm
   the rules (agreement raises confidence, disagreement lowers it).
3. **Model** - the existing local Ollama client, consulted *only* as a
   tie-break: when no rule fires, or when two incompatible intents tie in one
   clause. Its proposal is accepted only if it names known intents; code
   takes the decision, and an unavailable model never blocks a question.

Entities (metric, secondary metrics, dimensions, filters, period, comparison
period, grain, horizon, scenario parameters) are extracted by deterministic
code against the metric registry's synonyms, the governed dimensions and a
value index, with fuzzy matching for misspelled metric names. Nothing here
computes a business figure (SAFE-8).
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date

from catalog import MetricRegistry
from catalog.metric_resolver import MetricResolver
from contracts.models import MetricDefinition, MetricTimeGrain, Period
from contracts.v2 import (
    Entities,
    Horizon,
    IntentClassifierSignal,
    IntentModelSignal,
    IntentName,
    IntentRulesSignal,
    IntentSignals,
    ResolvedFilter,
    ScenarioAppliesTo,
    ScenarioParam,
    ScoredIntent,
)
from engines.horizon import extract_horizon
from engines.scenario import price_change_from_question
from semantic.metrics_v2 import all_metrics

DEFAULT_ANCHOR = "2018-08"
HISTORY_START = "2016-10"

# --------------------------------------------------------------------------- #
# Value index (GRD-8): literals a filter may take, never produced by a model
# --------------------------------------------------------------------------- #

BRAZIL_STATES = (
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA",
    "PB", "PE", "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO",
)
STATE_NAMES = {
    "sao paulo": "SP", "são paulo": "SP", "rio de janeiro": "RJ", "rio": "RJ", "minas gerais": "MG",
    "parana": "PR", "paraná": "PR", "santa catarina": "SC", "rio grande do sul": "RS", "bahia": "BA",
    "the south": ("PR", "SC", "RS"), "south": ("PR", "SC", "RS"),
}
DEFAULT_VALUES: dict[str, dict[str, str]] = {
    "payment_type": {"credit card": "credit_card", "boleto": "boleto", "voucher": "voucher", "debit card": "debit_card"},
    "carrier": {"correios": "correios", "jadlog": "jadlog", "loggi": "loggi", "total express": "total_express"},
    "channel": {"paid search": "paid_search", "social": "social", "display": "display", "email": "email", "affiliate": "affiliate"},
    "order_status": {"delivered": "delivered", "canceled": "canceled", "cancelled": "canceled", "shipped": "shipped"},
    "product_category": {
        "furniture": "moveis_decoracao", "home decor": "moveis_decoracao", "bed bath table": "cama_mesa_banho",
        "bed and bath": "cama_mesa_banho", "health and beauty": "beleza_saude", "beauty": "beleza_saude",
        "sports": "esporte_lazer", "sports and leisure": "esporte_lazer", "computers": "informatica_acessorios",
        "housewares": "utilidades_domesticas", "watches": "relogios_presentes", "toys": "brinquedos",
        "auto": "automotivo", "telephony": "telefonia", "perfumery": "perfumaria", "garden tools": "ferramentas_jardim",
        "cool stuff": "cool_stuff",
    },
}

# Attributes that exist in neither layer: they are named, never guessed (ABS-1).
ABSENT_ATTRIBUTES = {
    "age": "customer age", "gender": "customer gender", "income": "customer income", "ethnicity": "customer ethnicity",
    "argentina": "an Argentinian market", "mexico": "a Mexican market", "chile": "a Chilean market",
    "nps": "net promoter score", "net promoter": "net promoter score", "headcount": "employee data",
    "employees": "employee data", "salary": "salary data",
}

# --------------------------------------------------------------------------- #
# Intent rules
# --------------------------------------------------------------------------- #

_RULES: tuple[tuple[IntentName, str, float, str], ...] = (
    # scenario
    ("scenario", "what_if", 0.96, r"\bwhat if\b|\bwhat happens (?:to \w+ )?if\b|\bsuppose\b|\bimagine\b|\be se\b"),
    # forecast
    ("forecast", "forecast_verb", 0.95, r"\bforecast\w*\b|\bpredict\w*\b|\bproject(?:ion|ed)?\b|\bprevis"),
    ("forecast", "future_window", 0.9, r"\bwhat will\b.*\bbe\b|\bwill \w+(?: \w+)? (?:keep|continue)\b|\bwhere is .* heading\b|\bheading\b|\bhow many \w+ will\b|\bwill we have\b"),
    ("forecast", "next_period", 0.86, r"\b(?:expected|expect)\b.*\bnext (?:month|quarter|year)\b|\bin \d+ months\b|\bin 20(?:19|2\d)\b|\bnext \d+ (?:months|weeks|quarters)\b"),
    # prescriptive
    ("prescriptive", "should_we", 0.93, r"\bshould (?:we|i)\b|\bwhat (?:should|can) (?:we|i) do\b|\bwhat to do\b"),
    ("prescriptive", "prioritise", 0.9, r"\bprioriti[sz]e\b|\bwhere should we focus\b|\bfocus on\b|\bdeserve\b|\brecommend\w*\b"),
    ("prescriptive", "how_do_we", 0.88, r"\bhow (?:do|can|should) (?:we|i) (?:reduce|improve|increase|fix|grow|cut|lower)\b"),
    ("prescriptive", "watch", 0.9, r"\bwhat (?:should i|to|should we) watch\b|\bwhat to monitor\b|\btell me what to watch\b"),
    ("prescriptive", "target_segment", 0.9, r"\bwhich (?:customer )?segments? should\b|\bwhich \w+ should we target\b|\btarget\b.*\bsegment"),
    # impact
    ("impact", "cost", 0.92, r"\bcost(?:ing)? us\b|\bhow much did .* cost\b|\bwhat did it cost\b|\bwhat (?:are|is) .* costing\b|\bcosting\b"),
    ("impact", "worth", 0.88, r"\bworth\b|\bexposed\b|\bexposure\b|\bmattered most\b|\bhow far (?:are we )?off\b|\bshortfall\b|\breturn on\b|\bwhat did it add\b|\bhow big is\b|\bhow much of\b"),
    # diagnostic
    ("diagnostic", "why", 0.92, r"\bwhy\b|\bpor que\b"),
    ("diagnostic", "driver", 0.9, r"\bwhat (?:drove|caused|explains|is driving)\b|\bwhich \w+ drove\b|\bdrivers? of\b|\bdid (?:the )?\w+ cause\b|\bcontributed\b"),
    ("diagnostic", "unusual", 0.88, r"\bunusual\b|\banomal\w*\b|\boutliers?\b|\bwhat'?s wrong\b|\bwhat is wrong\b|\brising\b|\bfalling\b"),
    # descriptive
    ("descriptive", "spike_scan", 0.95, r"\b(?:spikes?|dips?|anomalies)\b.*\b(?:all|across|every|any)\b.*\b(?:months?|periods?|metrics?)\b"),
    ("descriptive", "trend", 0.86, r"\btrend\w*\b|\blooks? (?:like )?today\b|\bover time\b|\bby month\b|\bmonthly\b"),
    ("descriptive", "lookup", 0.82, r"\bhow many\b|\bhow much\b|\bwhat (?:was|were|is|are)\b|\bshow\b|\blist\b|\btotal\b|\bgive me\b"),
    ("descriptive", "compare", 0.84, r"\bcompare\w*\b|\bversus\b|\bvs\.?\b|\bcompared\b"),
    ("descriptive", "rank", 0.84, r"\btop\b|\bhighest\b|\blowest\b|\bbiggest\b|\blargest\b|\bbest\b|\bworst\b"),
    ("descriptive", "breakdown", 0.8, r"\bby (?:state|category|categories|channel|payment|month|carrier|seller|region)\b|\bbreak\w* (?:it )?down\b"),
    # discovery
    ("discovery", "what_data", 0.96, r"\bwhat (?:data|tables|datasets?|information)\b|\bdo you have\b|\bwhich (?:data|tables)\b"),
    ("discovery", "which_metrics", 0.95, r"\b(?:which|what) metrics\b|\bmetrics can you\b|\bwhat can you (?:calculate|measure)\b"),
    ("discovery", "coverage", 0.95, r"\bwhat (?:time )?period does the data\b|\bdata cover\b|\bdate range\b|\bhow far back\b"),
    ("discovery", "definition", 0.94, r"\bhow is \w+(?: \w+)? defined\b|\bdefinition of\b|\bwhat does \w+ mean\b|\bdifference between (?:gmv|revenue|aov)\b"),
    ("discovery", "dimensions", 0.94, r"\bwhat dimensions\b|\bcan i break \w+(?: \w+)? down\b|\bcan i (?:split|slice)\b"),
    ("discovery", "in_database", 0.93, r"\bin the (?:database|warehouse|data)\b"),
)
_COMPILED_RULES = tuple((intent, name, weight, re.compile(pattern)) for intent, name, weight, pattern in _RULES)

# Precedence inside one clause: the more specific intent wins a tie.
_PRECEDENCE: tuple[IntentName, ...] = (
    "scenario", "forecast", "prescriptive", "impact", "diagnostic", "discovery", "descriptive",
)
_CLASSIFIER_WORDS: dict[IntentName, tuple[str, ...]] = {
    "scenario": ("if", "suppose", "imagine", "happens", "raise", "lose", "halved", "doubled"),
    "forecast": ("forecast", "predict", "project", "next", "will", "heading", "future", "expected", "2019", "2020"),
    "prescriptive": ("should", "recommend", "prioritise", "prioritize", "focus", "target", "watch", "deserve", "do"),
    "impact": ("cost", "costing", "worth", "exposed", "shortfall", "impact", "attainment", "return", "matter"),
    "diagnostic": ("why", "drove", "caused", "driver", "drivers", "unusual", "anomaly", "wrong", "explain", "rising"),
    "descriptive": ("how", "many", "what", "was", "show", "list", "total", "trend", "top", "compare", "by"),
    "discovery": ("data", "tables", "metrics", "defined", "definition", "available", "have", "dimensions", "cover"),
}
_CLAUSE_SPLIT = re.compile(r"\s*(?:,\s*(?:and|then)\b|\band then\b|\band\b(?=\s+(?:what|why|how|is|was|tell|forecast|where|which|show|give|should))|[;?]|,)\s*")

# --------------------------------------------------------------------------- #
# Time
# --------------------------------------------------------------------------- #

_MONTHS = {
    name: index for index, names in enumerate((
        ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"), ("may",), ("june", "jun"),
        ("july", "jul"), ("august", "aug"), ("september", "sep", "sept"), ("october", "oct"),
        ("november", "nov"), ("december", "dec"),
    ), start=1) for name in names
}
_MONTH_WORD = r"(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")"
_MONTH_YEAR = re.compile(rf"\b{_MONTH_WORD}\s+(20\d{{2}})\b")
_BARE_MONTH = re.compile(rf"(?:^|\b(?:in|for|during|of|was|is|since|about|did)\s+|\bthe\s+){_MONTH_WORD}\b(?!\s+20\d{{2}})")
_QUARTER = re.compile(r"\bq([1-4])\s*(20\d{2})?\b")
_YEAR = re.compile(r"\b(20[12]\d)\b")
_GRAINS: tuple[tuple[str, MetricTimeGrain], ...] = (
    (r"\bdaily\b|\bby day\b|\bper day\b", "day"),
    (r"\bweekly\b|\bby week\b|\bper week\b", "week"),
    (r"\bmonthly\b|\bby month\b|\bper month\b|\beach month\b", "month"),
    (r"\bquarterly\b|\bby quarter\b|\bper quarter\b", "quarter"),
    (r"\byearly\b|\bannual\w*\b|\bby year\b", "year"),
)


def _month_start(text: str) -> date:
    year, month = (int(part) for part in text[:7].split("-"))
    return date(year, month, 1)


def _add_months(start: date, months: int) -> date:
    index = start.year * 12 + start.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


@dataclass(frozen=True)
class TimeReading:
    period: Period | None = None
    comparison: Period | None = None
    grain: MetricTimeGrain | None = None
    phrase: str | None = None
    assumptions: tuple[str, ...] = ()


def read_time(question: str, *, anchor: str = DEFAULT_ANCHOR) -> TimeReading:
    """Periods named in the question, clipped to the last complete month."""

    text = question.lower()
    last = _month_start(anchor)
    end_cap = _add_months(last, 1)
    grain = next((value for pattern, value in _GRAINS if re.search(pattern, text)), None)
    assumptions: list[str] = []
    periods: list[tuple[int, Period, str]] = []

    for match in _MONTH_YEAR.finditer(text):
        start = date(int(match.group(2)), _MONTHS[match.group(1)], 1)
        periods.append((match.start(), Period(start=start, end=_add_months(start, 1)), match.group(0)))
    for match in _QUARTER.finditer(text):
        year = int(match.group(2)) if match.group(2) else last.year
        start = date(year, (int(match.group(1)) - 1) * 3 + 1, 1)
        periods.append((match.start(), Period(start=start, end=_add_months(start, 3)), match.group(0)))
    taken = [(position, position + len(phrase)) for position, _, phrase in periods]
    for match in _YEAR.finditer(text):
        if any(low <= match.start() < high for low, high in taken):
            continue
        year = int(match.group(1))
        periods.append((match.start(), Period(start=date(year, 1, 1), end=date(year + 1, 1, 1)), match.group(0)))
    if not periods:
        for match in _BARE_MONTH.finditer(text):
            month = _MONTHS[match.group(1)]
            year = last.year if month <= last.month else last.year - 1
            start = date(year, month, 1)
            periods.append((match.start(), Period(start=start, end=_add_months(start, 1)), match.group(1)))
            assumptions.append(f"'{match.group(1)}' was read as {start:%B %Y}, the most recent complete one.")

    relative = None
    if re.search(r"\blast (?:complete )?month\b|\bthis month\b", text):
        relative = (Period(start=last, end=end_cap), "last month")
    elif re.search(r"\blast quarter\b|\blast 3 months\b|\blast three months\b", text):
        relative = (Period(start=_add_months(last, -2), end=end_cap), "last 3 complete months")
    elif re.search(r"\blast 12 months\b|\blast year\b(?!.*\bvs\b)|\btoday\b|\bnow\b|\bthis year\b|\bytd\b|\byear to date\b", text):
        if re.search(r"\bthis year\b|\bytd\b|\byear to date\b", text):
            relative = (Period(start=date(last.year, 1, 1), end=end_cap), "year to date")
        else:
            relative = (Period(start=_add_months(last, -11), end=end_cap), "last 12 complete months")
    if relative is not None and not periods:
        periods.append((0, relative[0], relative[1]))
        assumptions.append(f"'{relative[1]}' was read as {relative[0].start:%Y-%m} to {_add_months(relative[0].end, -1):%Y-%m}.")

    periods.sort(key=lambda item: item[0])
    clipped: list[Period] = []
    for _, period, phrase in periods:
        if period.start >= end_cap:
            clipped.append(period)
            continue
        if period.end > end_cap:
            assumptions.append(
                f"{phrase} was clipped to end at {anchor}, the last complete month; later months are incomplete."
            )
            period = Period(start=period.start, end=end_cap)
        clipped.append(period)
    unique: list[Period] = []
    for period in clipped:
        if period not in unique:
            unique.append(period)
    current = unique[0] if unique else None
    comparison = unique[1] if len(unique) > 1 else None
    # "compare 2018 to 2017" keeps 2018 current; "between Q1 and Q2" makes Q2 current.
    explicit_order = re.search(r"\bcompare\w* (?:20\d\d|q[1-4]|\w+ 20\d\d) (?:to|with|against|versus|vs)\b", text)
    if current is not None and comparison is not None and current.start < comparison.start and not explicit_order:
        current, comparison = comparison, current
    if current is not None and comparison is not None:
        current_length = (current.end.year - current.start.year) * 12 + current.end.month - current.start.month
        comparison_length = (comparison.end.year - comparison.start.year) * 12 + comparison.end.month - comparison.start.month
        if current_length != comparison_length and comparison_length > current_length:
            aligned = Period(start=comparison.start, end=_add_months(comparison.start, current_length))
            assumptions.append(
                f"The comparison window was aligned to the same {current_length} months so the periods are like for like."
            )
            comparison = aligned
    phrase = ", ".join(item[2] for item in periods) or None
    return TimeReading(period=current, comparison=comparison, grain=grain, phrase=phrase, assumptions=tuple(assumptions))


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #


def _normalize(text: str) -> str:
    lowered = text.lower().replace("&", " and ")
    lowered = re.sub(r"[_/]+", " ", lowered)
    lowered = re.sub(r"[^\w\s%+.-]", " ", lowered)
    return " ".join(lowered.split())


def _phrase_in(text: str, phrase: str) -> int | None:
    match = re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text)
    return match.start() if match else None


@dataclass
class ValueIndex:
    """Allowlisted filter literals per governed dimension."""

    values: dict[str, dict[str, str]] = field(default_factory=lambda: {key: dict(value) for key, value in DEFAULT_VALUES.items()})

    def add_categories(self, rows: Iterable[tuple[str, str | None]]) -> None:
        for name, english in rows:
            if not name:
                continue
            self.values["product_category"][name.replace("_", " ")] = name
            if english:
                self.values["product_category"][english.replace("_", " ").lower()] = name

    def link(self, text: str) -> list[ResolvedFilter]:
        found: list[ResolvedFilter] = []
        for code in BRAZIL_STATES:
            if re.search(rf"(?<![\w']){code}(?![\w'])", text):
                found.append(ResolvedFilter(dimension="customer_state", operator="=", values=(code,), source_phrase=code, link_confidence=0.98))
        lowered = text.lower()
        for name, code in STATE_NAMES.items():
            if _phrase_in(lowered, name) is not None and not any(item.source_phrase.lower() == name for item in found):
                values = code if isinstance(code, tuple) else (code,)
                if any(set(values) <= set(item.values) for item in found):
                    continue
                found.append(ResolvedFilter(dimension="customer_state", operator="in" if len(values) > 1 else "=",
                                            values=values, source_phrase=name, link_confidence=0.9))
        for dimension, mapping in self.values.items():
            for phrase, value in sorted(mapping.items(), key=lambda item: -len(item[0])):
                if _phrase_in(lowered, phrase) is not None and not any(item.dimension == dimension and value in item.values for item in found):
                    found.append(ResolvedFilter(dimension=dimension, operator="=", values=(value,), source_phrase=phrase, link_confidence=0.92))
        merged: dict[str, ResolvedFilter] = {}
        for item in found:
            if item.dimension in merged:
                prior = merged[item.dimension]
                values = tuple(dict.fromkeys((*prior.values, *item.values)))
                merged[item.dimension] = ResolvedFilter(dimension=item.dimension, operator="in" if len(values) > 1 else "=",
                                                        values=values, source_phrase=f"{prior.source_phrase}, {item.source_phrase}",
                                                        link_confidence=min(prior.link_confidence, item.link_confidence))
            else:
                merged[item.dimension] = item
        return list(merged.values())


@dataclass(frozen=True)
class MetricMention:
    metric_id: str
    position: int
    phrase: str
    fuzzy: bool = False


_NON_METRIC_PHRASES = (
    "customer state", "customer states", "customer city", "customer segment", "customer segments",
    "customer age", "customer gender", "customer unique id", "customer id", "customers are in the database",
    "target", "targeting", "order status", "order statuses", "price change", "regional target",
)

_DIMENSION_WORDS = {
    "customer_state": ("state", "states", "region", "regions", "uf"),
    "customer_city": ("city", "cities"),
    "product_category": ("category", "categories", "product category", "product categories"),
    "payment_type": ("payment type", "payment method", "payment types", "payment"),
    "order_status": ("status", "order status"),
    "seller_state": ("seller state", "seller states"),
    "channel": ("channel", "channels", "marketing channel"),
    "carrier": ("carrier", "carriers"),
    "segment": ("segment", "segments"),
}
_STOPWORDS = frozenset(
    ["a", "an", "the", "of", "in", "on", "for", "by", "to", "and", "or", "is", "was", "were", "are", "be", "been", "what", "why", "how", "which", "who", "whom", "when", "where", "will", "would", "should", "could", "can", "do", "did", "does", "me", "my", "we", "our", "us", "you", "your", "it", "its", "this", "that", "these", "those", "than", "then", "there", "their", "from", "with", "into", "over", "across", "all", "any", "each", "every", "per", "vs", "versus", "about", "last", "next", "month", "months", "year", "years", "quarter", "quarters", "week", "weeks", "day", "days", "show", "give", "tell", "list", "total", "top", "much", "many", "most", "more", "less", "up", "down", "rise", "fall", "drop", "if", "happens", "raise", "cut", "lose", "forecast", "trend", "look", "today", "now", "please", "numbers", "number", "data", "also", "just", "only", "so"]
)


class EntityExtractor:
    """Deterministic entity extraction over the semantic layer."""

    def __init__(self, registry: MetricRegistry | None = None, *, values: ValueIndex | None = None,
                 anchor: str = DEFAULT_ANCHOR) -> None:
        self.registry = registry or all_metrics()
        self.values = values or ValueIndex()
        self.anchor = anchor
        self._resolver = MetricResolver(self.registry, client=None)
        self._phrases: list[tuple[str, str]] = []
        for metric in self.registry.metrics:
            for phrase in (metric.metric_id.replace("_", " "), metric.name, *metric.synonyms):
                self._phrases.append((_normalize(phrase), metric.metric_id))
        # Common phrasings the registry does not list.
        for phrase, metric_id in (("orders", "order_count"), ("order", "order_count"), ("cancellations", "cancellation_rate"),
                                  ("cancellation", "cancellation_rate"), ("review scores", "review_score"),
                                  ("review score", "review_score"), ("reviews", "review_score"), ("customers", "customer_count"),
                                  ("items", "item_count"), ("returns", "return_rate"), ("prices", "price"),
                                  ("conversions", "conversion_rate"), ("traffic", "sessions"), ("spend", "marketing_spend"),
                                  ("stockouts", "stockout_rate"), ("stockout", "stockout_rate"), ("targets", "target_attainment"),
                                  ("regional targets", "target_attainment"), ("shipping", "freight_value"),
                                  ("gross revenue", "gross_vs_net"), ("net revenue", "revenue"), ("business", "business")):
            if metric_id in {"price", "gross_vs_net", "business"} or self.registry.get(metric_id) is not None:
                self._phrases.append((phrase, metric_id))
        self._phrases.sort(key=lambda item: -len(item[0]))
        self._vocabulary = sorted({phrase for phrase, metric_id in self._phrases if " " not in phrase and len(phrase) >= 4
                                   and self.registry.get(metric_id) is not None})

    def metric(self, metric_id: str) -> MetricDefinition | None:
        return self.registry.get(metric_id)

    def mentions(self, text: str) -> list[MetricMention]:
        normalized = _normalize(text)
        taken: list[tuple[int, int]] = []
        # Dimension and value phrases ("customer state", "customer segment", "SP") are not metrics.
        for phrase in _NON_METRIC_PHRASES:
            for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
                taken.append((match.start(), match.end()))
        found: list[MetricMention] = []
        for phrase, metric_id in self._phrases:
            for match in re.finditer(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized):
                span = (match.start(), match.end())
                if any(low < span[1] and span[0] < high for low, high in taken):
                    continue
                taken.append(span)
                found.append(MetricMention(metric_id, match.start(), phrase))
        for match in re.finditer(r"[a-z]{4,}", normalized):
            word = match.group(0)
            if word in _STOPWORDS or any(low <= match.start() < high for low, high in taken):
                continue
            if len(word) < 5:
                continue
            close = difflib.get_close_matches(word, self._vocabulary, n=1, cutoff=0.84)
            # A plural or singular of a known phrase is not a typo, and is not a metric on its own.
            if close and close[0] != word and not (close[0].startswith(word) or word.startswith(close[0])):
                metric_id = next(metric for phrase, metric in self._phrases if phrase == close[0])
                found.append(MetricMention(metric_id, match.start(), word, fuzzy=True))
        found.sort(key=lambda item: item.position)
        ordered: list[MetricMention] = []
        for item in found:
            if item.metric_id not in {mention.metric_id for mention in ordered}:
                ordered.append(item)
        return ordered

    def dimensions(self, text: str, metric: MetricDefinition | None) -> list[str]:
        normalized = _normalize(text)
        allowed = {dimension.name for dimension in metric.allowed_dimensions} if metric is not None else set()
        synonyms: dict[str, tuple[str, ...]] = dict(_DIMENSION_WORDS)
        if metric is not None:
            for dimension in metric.allowed_dimensions:
                synonyms[dimension.name] = tuple(dict.fromkeys((*synonyms.get(dimension.name, ()), *dimension.synonyms)))
        found: list[tuple[int, str]] = []
        for name, words in synonyms.items():
            if name in {"month", "year"}:
                continue
            for word in sorted(words, key=len, reverse=True):
                pattern = rf"\b(?:by|per|across|each|which|top \d+|top|biggest|best|worst|highest|lowest|every|for each|break\w* (?:it |that |this )?down by|into)\s+(?:\w+\s+)?{re.escape(_normalize(word))}\b"
                match = re.search(pattern, normalized)
                if match:
                    found.append((match.start(), name))
                    break
        found.sort()
        return list(dict.fromkeys(name for _, name in found))

    def scenario_params(self, text: str, metric_id: str | None) -> list[ScenarioParam]:
        lowered = text.lower()
        params: list[ScenarioParam] = []
        price = price_change_from_question(text)
        if price is not None:
            params.append(ScenarioParam(target="price", kind="multiplicative", value=round(1 + price / 100.0, 10),
                                        source_phrase=_phrase_around(lowered, "price")))
        for match in re.finditer(r"\b([a-z ]{2,30}?)\s+(rises?|rose|increases?|grows?|grew|improves?|improved|falls?|fell|drops?|declines?|decreases?)\s+(?:by\s+)?(\d+(?:\.\d+)?)\s*%",
                                 lowered):
            subject = match.group(1).strip()
            if "price" in subject:
                continue
            sign = -1 if match.group(2).startswith(("fall", "fell", "drop", "decl", "decr")) else 1
            target = self._target_for(subject) or metric_id or subject.split()[-1]
            params.append(ScenarioParam(target=target, kind="multiplicative", value=round(1 + sign * float(match.group(3)) / 100.0, 10),
                                        source_phrase=match.group(0).strip()))
        for match in re.finditer(r"\b(?:grew|grows|rose|went|goes|increased?) to (\d+(?:\.\d+)?)\s*%", lowered):
            subject = lowered[: match.start()].split()[-3:] if match.start() else []
            target = self._target_for(" ".join(subject)) or "payment_type"
            params.append(ScenarioParam(target=target, kind="absolute", value=float(match.group(1)) / 100.0, source_phrase=match.group(0)))
        if re.search(r"\bhalved\b|\bhalve\b|\bcut in half\b", lowered):
            params.append(ScenarioParam(target=metric_id or "metric", kind="multiplicative", value=0.5, source_phrase="halved"))
        if re.search(r"\bdoubled\b|\bdouble\b", lowered):
            params.append(ScenarioParam(target=metric_id or "metric", kind="multiplicative", value=2.0, source_phrase="doubled"))
        lose = re.search(r"\blose (\w+)(?: entirely)?\b|\blost (\w+)\b|\bwithout (\w+)\b", text)
        if lose:
            token = next(group for group in lose.groups() if group)
            filters = self.values.link(token)
            if filters:
                params.append(ScenarioParam(target=metric_id or "revenue", kind="remove",
                                            value=0.0, applies_to=ScenarioAppliesTo(dimension=filters[0].dimension, values=filters[0].values),
                                            source_phrase=lose.group(0)))
            elif re.search(r"\b(?:it|them|that)\b", token):
                params.append(ScenarioParam(target=metric_id or "revenue", kind="remove", value=0.0,
                                            applies_to=ScenarioAppliesTo(dimension="customer_state", values=("top",)),
                                            source_phrase=lose.group(0)))
        if re.search(r"\brestor\w*\b", lowered) and "spend" in lowered:
            params.append(ScenarioParam(target="marketing_spend", kind="additive", value=0.0, source_phrase="restored the marketing spend we cut"))
        if re.search(r"\beliminat\w*\b|\bremov\w* (?:the )?\w+", lowered) and not any(param.kind == "remove" for param in params):
            subject = re.search(r"\b(?:eliminat\w*|remov\w*) (?:the |all )?(\w+)", lowered)
            target = self._target_for(subject.group(1)) if subject else None
            params.append(ScenarioParam(target=target or "stockout_rate", kind="absolute", value=0.0,
                                        source_phrase=subject.group(0) if subject else "eliminate"))
        if re.search(r"\blaunch\w* in (\w+)", lowered):
            place = re.search(r"\blaunch\w* in (\w+)", lowered).group(1)  # type: ignore[union-attr]
            params.append(ScenarioParam(target="market", kind="additive", value=0.0, source_phrase=f"launched in {place}"))
        return params

    def _target_for(self, subject: str) -> str | None:
        mentions = self.mentions(subject)
        return mentions[0].metric_id if mentions and self.registry.get(mentions[0].metric_id) is not None else None


def _phrase_around(text: str, word: str) -> str:
    position = text.find(word)
    if position < 0:
        return text[:60]
    return text[max(0, position - 25): position + 30].strip()


# --------------------------------------------------------------------------- #
# Intent result assembly
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ClauseIntent:
    intent: IntentName
    score: float
    span: str
    rules: tuple[str, ...]


@dataclass(frozen=True)
class Extraction:
    """Everything the extractor read, before grounding decides."""

    question: str
    intents: tuple[ScoredIntent, ...]
    entities: Entities
    signals: IntentSignals
    confidence: float
    reason: str
    metric_mentions: tuple[MetricMention, ...]
    time: TimeReading
    rules_matched: tuple[str, ...]
    absent: tuple[str, ...]
    special: tuple[str, ...]
    ungoverned_term: str | None


def split_clauses(question: str) -> list[str]:
    parts = [part.strip() for part in _CLAUSE_SPLIT.split(question) if part and part.strip()]
    return parts or [question.strip()]


def clause_intents(clause: str) -> list[ClauseIntent]:
    text = clause.lower()
    hits: dict[IntentName, tuple[float, list[str]]] = {}
    for intent, name, weight, pattern in _COMPILED_RULES:
        if pattern.search(text):
            score, names = hits.get(intent, (0.0, []))
            hits[intent] = (max(score, weight), [*names, name])
    return [ClauseIntent(intent, score, clause, tuple(names)) for intent, (score, names) in hits.items()]


def classifier_scores(question: str) -> dict[IntentName, float]:
    words = re.findall(r"[a-z0-9]+", question.lower())
    scores: dict[IntentName, float] = {}
    for intent, vocabulary in _CLASSIFIER_WORDS.items():
        hits = sum(1 for word in words if word in vocabulary)
        if hits:
            scores[intent] = round(min(0.95, 0.45 + 0.15 * hits), 4)
    return scores


_MODEL_PROMPT = (
    "Classify the analytics question into one or more of these intents: discovery, clarify, descriptive, "
    "diagnostic, impact, forecast, scenario, prescriptive. Return JSON: {\"intents\": [...], \"confidence\": 0-1}. "
    "Never compute or invent numbers."
)


class IntentExtractor:
    """Rules first, classifier to confirm, local model only as a tie-break."""

    def __init__(self, *, entities: EntityExtractor | None = None, client: object | None = None,
                 anchor: str = DEFAULT_ANCHOR) -> None:
        self.entities = entities or EntityExtractor(anchor=anchor)
        self.client = client
        self.anchor = anchor

    def extract(self, question: str) -> Extraction:
        text = question.strip()
        lowered = text.lower()
        clauses = split_clauses(text)
        per_clause = [sorted(clause_intents(clause), key=lambda item: (-item.score, _PRECEDENCE.index(item.intent))) for clause in clauses]
        chosen: list[ClauseIntent] = []
        tie_breaks: list[tuple[str, list[ClauseIntent]]] = []
        for clause, hits in zip(clauses, per_clause, strict=True):
            if not hits:
                continue
            top = _pick(hits)
            rivals = [hit for hit in hits if hit.intent != top.intent and abs(hit.score - top.score) < 0.005
                      and {hit.intent, top.intent} not in _COMPATIBLE]
            if rivals:
                tie_breaks.append((clause, [top, *rivals]))
            chosen.append(top)
            # Secondary intents asked in the same clause ("why ... and what did it cost").
            for hit in hits:
                if hit.intent in {"impact", "forecast", "scenario", "prescriptive"} and hit.intent != top.intent and hit.score >= 0.88:
                    chosen.append(hit)

        rules_matched = tuple(dict.fromkeys(name for hits in per_clause for hit in hits for name in hit.rules))
        classifier = classifier_scores(text)
        model_signal: IntentModelSignal | None = None
        if not chosen or tie_breaks:
            model_signal, proposed = self._model(text)
            if proposed:
                if not chosen:
                    chosen = [ClauseIntent(intent, 0.75, text, ("model_tie_break",)) for intent in proposed]
                else:
                    for clause, candidates in tie_breaks:
                        winner = next((item for item in candidates if item.intent in proposed), None)
                        if winner is not None:
                            chosen = [winner if item.span == clause and item in candidates else item for item in chosen]
            elif tie_breaks:
                pass  # deterministic precedence already chose; the model was unavailable or abstained

        special: list[str] = []
        if "spike_scan" in rules_matched:
            special.append("spike_scan")
        if re.search(r"\b(?:churn\w*|at risk|likely to leave|retention)\b", lowered):
            special.append("risk")
        if re.search(r"\binventory\b|\bstock\b|\breorder\b|\brestock\b", lowered):
            special.append("inventory")
        if re.search(r"\bsegments?\b", lowered):
            special.append("segments")
        if re.search(r"\bdeliver\w*\b|\bcarrier\b|\bsla\b|\bdelays?\b", lowered):
            special.append("delivery")
        if re.search(r"\bsummar\w*\b|\boverview\b|\bhow'?s business\b|\bhow is business\b|\bhow are sales doing\b|\bhow are we doing\b|\bgive me the numbers\b|\btell me about\b|\bperformance\b|\bbest and worst\b|\bshow growth\b|\bis growth good\b|\banything unusual\b|\bbreak it down\b|\bnumbers for\b|\brecent\w*\b|\blately\b", lowered):
            special.append("vague")

        intents = _order(chosen)
        mentions = tuple(self.entities.mentions(text))
        governed = [mention for mention in mentions if self.entities.metric(mention.metric_id) is not None]
        metric = self.entities.metric(governed[0].metric_id) if governed else None
        resolution = self._resolver_reading(text)
        if metric is None and resolution is not None and resolution.definition is not None:
            metric = resolution.definition
        time = read_time(text, anchor=self.anchor)
        dimensions = self.entities.dimensions(text, metric)
        if resolution is not None:
            for item in resolution.resolved_dimensions:
                if item.allowed and item.requested not in dimensions and item.requested not in {"month", "year"}:
                    dimensions.append(item.requested)
        filters = self.entities.values.link(text)
        intent_names = [item.intent for item in intents]
        horizon = None
        if "forecast" in intent_names:
            parsed = extract_horizon(text, anchor=self.anchor, grain=time.grain if time.grain in {"day", "week", "month"} else "month")
            horizon = parsed.horizon
            if horizon is None and time.period is not None and time.period.start > _month_start(self.anchor):
                months = (time.period.end.year - _month_start(self.anchor).year) * 12 + time.period.end.month - _month_start(self.anchor).month - 1
                horizon = Horizon(periods=max(1, months), grain="month", anchor=self.anchor)
            if horizon is None:
                horizon = Horizon(periods=3, grain="month", anchor=self.anchor)
        try:
            scenario = self.entities.scenario_params(text, metric.metric_id if metric else None) if "scenario" in intent_names else []
        except ValueError:  # a parameter the contract rejects is not extracted; grounding then asks
            scenario = []
        if "scenario" in intent_names and not scenario:
            intents = tuple(item for item in intents if item.intent != "scenario") or (ScoredIntent(intent="descriptive", score=0.6, span=text),)
            special.append("scenario_without_parameter")
        absent = tuple(dict.fromkeys(label for word, label in ABSENT_ATTRIBUTES.items() if re.search(rf"\b{re.escape(word)}\b", lowered)))
        ungoverned = None
        if metric is None:
            ungoverned = next((mention.phrase for mention in mentions), None)
            if ungoverned is None:
                if "delivery" in special:
                    ungoverned = "delivery delays"
                elif "segments" in special:
                    ungoverned = "customer segments"
                elif "inventory" in special:
                    ungoverned = "inventory"
        period = time.period
        if horizon is not None and period is not None and period.start > _month_start(self.anchor):
            period = None  # a future year is the horizon, not a history window
        entities = Entities(
            metric_id=metric.metric_id if metric is not None else None,
            secondary_metric_ids=tuple(mention.metric_id for mention in governed[1:] if mention.metric_id != (metric.metric_id if metric else None)),
            dimensions=tuple(dimensions),
            filters=tuple(filters),
            period=period,
            comparison_period=time.comparison if horizon is None or time.comparison is None else None,
            grain=time.grain,
            horizon=horizon,
            scenario_params=tuple(scenario) if any(item.intent == "scenario" for item in intents) else (),
            action_intent="prescriptive" in [item.intent for item in intents],
        )
        agreement = bool(intents) and intents[0].intent in classifier and max(classifier, key=classifier.get) in {item.intent for item in intents}  # type: ignore[arg-type]
        top_score = intents[0].score if intents else 0.0
        confidence = round(min(0.99, top_score + (0.03 if agreement else -0.05)), 4) if intents else 0.0
        signals = IntentSignals(
            rules=IntentRulesSignal(matched=rules_matched, intents=tuple(dict.fromkeys(hit.intent for hits in per_clause for hit in hits))),
            classifier=IntentClassifierSignal(intents=tuple(ScoredIntent(intent=name, score=score) for name, score in
                                                            sorted(classifier.items(), key=lambda item: -item[1]))),
            model=model_signal,
            agreement=agreement,
        )
        reason = _reason(intents, rules_matched, model_signal)
        return Extraction(text, intents, entities, signals, confidence, reason, mentions, time, rules_matched, absent,
                          tuple(dict.fromkeys(special)), ungoverned)

    def _resolver_reading(self, text: str):
        try:
            return self.entities._resolver.resolve(text, use_model=False)
        except Exception:  # the resolver is advisory here; grounding decides
            return None

    def _model(self, text: str) -> tuple[IntentModelSignal | None, list[IntentName]]:
        if self.client is None or self.client is False:
            return None, []
        try:
            raw = self.client.chat_json([{"role": "system", "content": _MODEL_PROMPT}, {"role": "user", "content": text}])  # type: ignore[attr-defined]
        except Exception:
            return IntentModelSignal(proposed=(), confidence=0.0), []
        payload = raw[0] if isinstance(raw, tuple) else raw
        if not isinstance(payload, Mapping):
            return IntentModelSignal(proposed=(), confidence=0.0), []
        proposed = [item for item in payload.get("intents", []) if item in _PRECEDENCE]
        try:
            confidence = min(1.0, max(0.0, float(payload.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        return IntentModelSignal(proposed=tuple(dict.fromkeys(proposed)), confidence=confidence), list(dict.fromkeys(proposed))


_COMPATIBLE = (
    {"descriptive", "diagnostic"},
)


def _pick(hits: list[ClauseIntent]) -> ClauseIntent:
    best = max(hit.score for hit in hits)
    tied = [hit for hit in hits if best - hit.score < 0.03]
    return min(tied, key=lambda hit: _PRECEDENCE.index(hit.intent))


def _order(chosen: Iterable[ClauseIntent]) -> tuple[ScoredIntent, ...]:
    seen: dict[IntentName, ScoredIntent] = {}
    for item in chosen:
        if item.intent not in seen:
            seen[item.intent] = ScoredIntent(intent=item.intent, score=round(item.score, 4), span=item.span[:200])
    ordered = list(seen.values())
    # A prescriptive question about a diagnosed change also needs the impact sized (scope.md K3).
    names = [item.intent for item in ordered]
    if "prescriptive" in names and "diagnostic" in names and "impact" not in names:
        ordered.insert(names.index("prescriptive"), ScoredIntent(intent="impact", score=0.85, span=None))
    return tuple(ordered)


def _reason(intents: tuple[ScoredIntent, ...], rules: tuple[str, ...], model: IntentModelSignal | None) -> str:
    if not intents:
        return "No intent rule matched the question."
    names = " + ".join(item.intent for item in intents)
    source = f"rules {', '.join(rules)}" if rules else "the local model's tie-break"
    if model is not None and model.proposed:
        source += " (tie broken by the local model)"
    return f"Treated as {names}, from {source}."


def prd_label(intents: Iterable[IntentName], comparison: bool) -> str:
    names = list(intents)
    if not names:
        return "Descriptive"
    primary = names[0]
    if primary in {"diagnostic", "impact"}:
        return "Diagnostic"
    if primary in {"scenario", "prescriptive"}:
        return "Prescriptive"
    return "Comparative" if comparison else "Descriptive"


def describe_period(period: Period | None) -> str:
    if period is None:
        return "no window"
    last = _add_months(period.end, -1)
    if last == period.start:
        return f"{period.start:%Y-%m}"
    return f"{period.start:%Y-%m} to {last:%Y-%m}"


__all__ = [
    "ABSENT_ATTRIBUTES",
    "DEFAULT_ANCHOR",
    "EntityExtractor",
    "Extraction",
    "IntentExtractor",
    "TimeReading",
    "ValueIndex",
    "classifier_scores",
    "clause_intents",
    "describe_period",
    "prd_label",
    "read_time",
    "split_clauses",
]
