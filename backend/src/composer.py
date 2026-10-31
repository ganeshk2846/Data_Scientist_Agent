"""Compose the V2 answer from step results only (SAFE-3, SAFE-8, EN-1..6).

The narrative is assembled by fixed templates from engine reports and SQL
rows. Every figure it shows is first registered as a ``LedgerClaim`` - at
exactly the precision it is displayed - with the query or engine run that
produced it, and the narrative then passes through the existing
``FactChecker``: any sentence holding a number that is not a claim is
removed. No model writes any part of the answer.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from contracts.models import (
    ActionOption,
    BlockBlock,
    ClaimNumber,
    ClaimSource,
    EnvelopeQueryRecord,
    EnvelopeScope,
    EvidenceBlock,
    Ledger,
    LedgerClaim,
    MethodStep,
    Provenance,
    RefusalBlock,
    RouteSummary,
    RunMetrics,
)
from contracts.v2 import (
    AnswerEnvelopeV2,
    ClarificationRequest,
    FollowUpSuggestion,
    IntentResult,
    Plan,
    ResolvedQuestion,
    StepResultSummary,
    ToolResult,
)
from engines.diagnostic import CAUSAL_BOUNDARY
from engines.report import EngineReport
from evidence.ledger import _NUMBER, FactChecker, _token_value, format_number
from intent import describe_period
from viz import build_visualizations

_MONEY = frozenset({"revenue", "gmv", "aov", "freight_value", "marketing_spend", "R$"})
_LABELS = {"gmv": "GMV", "aov": "AOV", "revenue": "revenue", "order_count": "order count", "sla_breach_rate": "SLA breach rate"}


def _round(value: float, digits: int = 2) -> float:
    return float(round(value, digits))


@dataclass
class Claims:
    """Collects ledger claims while the narrative is written."""

    claims: list[LedgerClaim] = field(default_factory=list)

    def add(self, text: str, values: list[float], source: tuple[str, str], *, grade: int = 1, kind: str = "fact",
            unit: str | None = None) -> str:
        numbers = []
        seen = set()
        for value in values:
            if value is None or not math.isfinite(value):
                continue
            key = round(value, 9)
            if key in seen:
                continue
            seen.add(key)
            numbers.append(ClaimNumber(token=format_number(value), value=float(value), unit=unit))
        claim_id = f"C{len(self.claims) + 1}"
        self.claims.append(LedgerClaim(claim_id=claim_id, text=text[:500], numbers=tuple(numbers),
                                       source=ClaimSource(type=source[0], id=source[1]), grade=max(0, min(4, grade)), kind=kind))  # type: ignore[arg-type]
        return claim_id


def _fmt(value: float | None, unit: str = "", digits: int = 2) -> tuple[str, float | None]:
    if value is None or not math.isfinite(value):
        return "n/a", None
    if digits >= 2 and 0 < abs(value) < 0.1:
        digits = 4  # small rates and ratio components keep four decimals instead of reading as 0
    rounded = _round(value, digits)
    token = format_number(rounded)
    if unit in _MONEY or unit == "R$":
        return f"R$ {token}", rounded
    if unit == "%":
        return f"{token}%", rounded
    return token, rounded


def _source(result: ToolResult) -> tuple[str, str]:
    if result.provenance.source == "engine" and result.analyst_output is not None:
        return ("artifact", f"{result.step_id}:{result.tool}")
    if result.provenance.query_ids:
        return ("query", result.provenance.query_ids[0])
    return ("artifact", f"{result.step_id}:{result.tool}")


def _period_text(period) -> str:
    if period is None:
        return "the default window"
    return describe_period(period)


# --------------------------------------------------------------------------- #
# Per-step sentences
# --------------------------------------------------------------------------- #


def _number(report: EngineReport, name: str) -> float | None:
    try:
        return report.number(name)
    except KeyError:
        return None


def _sentences(step, result: ToolResult, report: EngineReport, claims: Claims, resolved: ResolvedQuestion | None) -> tuple[list[str], list[str]]:
    """Sentences and claim ids for one successful step."""
    metric = (step.params.get("metric_id") or step.params.get("metric") or step.params.get("kpi")
              or (resolved.metric_id if resolved else None) or "the metric")
    label = _LABELS.get(str(metric), str(metric).replace("_", " "))
    unit = "R$" if metric in _MONEY else ""
    source = _source(result)
    out: list[str] = []
    ids: list[str] = []

    def say(template: str, figures: list[tuple[float | None, str, int]], *, grade: int = 1, kind: str = "fact") -> None:
        rendered = []
        values = []
        for value, figure_unit, digits in figures:
            text, rounded = _fmt(value, figure_unit, digits)
            rendered.append(text)
            if rounded is not None:
                values.append(rounded)
        if any(item == "n/a" for item in rendered):
            return
        sentence = template.format(*rendered)
        ids.append(claims.add(sentence, values, source, grade=grade, kind=kind))
        out.append(sentence)

    method = report.method
    if result.tool == "catalog":
        rows = report.tables[0].rows if report.tables else ()
        if method == "catalog.warehouse":
            synthetic = [row[0] for row in rows if row[1] == "synthetic"]
            real = [row[0] for row in rows if row[1] == "real"]
            total = len(rows)
            sentence = (f"The warehouse holds {total} tables: {len(real)} real Olist tables ({', '.join(real[:9])}) and "
                        f"{len(synthetic)} synthetic tables ({', '.join(synthetic[:10])}), each labelled synthetic.")
            ids.append(claims.add(sentence, [float(total), float(len(real)), float(len(synthetic))], ("query", "catalog"), kind="fact"))
            out.append(sentence)
            for row in rows[:20]:
                if row[2] is not None:
                    span = f", {row[3]} to {row[4]}" if row[3] else ""
                    text = f"{row[0]}: {format_number(float(row[2]))} rows{span}."
                    years = [float(part) for part in re.findall(r"\b(20\d\d)\b", span)]
                    months = [float(int(part)) for part in re.findall(r"-(\d\d)", span)]
                    ids.append(claims.add(text, [float(row[2]), *years, *months], ("query", "catalog")))
                    out.append(text)
        elif method == "catalog.metric_definition":
            for row in rows:
                sentence = f"{row[1]} ({row[0]}) is computed from {row[2]}; it can be broken down by {row[3]}."
                ids.append(claims.add(sentence, [], ("artifact", "catalog")))
                out.append(sentence)
        elif method == "catalog.table":
            for sentence in _table_sentences(dict((row[0], row[1]) for row in rows if row[0] != "example"),
                                             [row[1] for row in rows if row[0] == "example"]):
                ids.append(claims.add(sentence, _catalog_numbers(sentence), ("query", "catalog")))
                out.append(sentence)
        elif method == "catalog.metrics":
            real = [row for row in rows if row[2] == "real"]
            synthetic = [row for row in rows if row[2] == "synthetic"]
            sentence = (f"You can ask about {len(rows)} governed metrics: {len(real)} on the real Olist data "
                        f"({', '.join(row[0] for row in real)}) and {len(synthetic)} on synthetic tables "
                        f"({', '.join(row[0] for row in synthetic)}), which are labelled synthetic in every answer.")
            ids.append(claims.add(sentence, [float(len(rows)), float(len(real)), float(len(synthetic))], ("query", "catalog"), kind="fact"))
            out.append(sentence)
            for row in rows:
                split = f", by {row[4]}" if row[4] else ""
                example = f" Try: \u201c{row[5]}\u201d" if row[5] else ""
                sentence = f"{row[1]} ({row[0]}, {row[2]}) from {row[3]}{split}.{example}"
                ids.append(claims.add(sentence, _catalog_numbers(sentence), ("artifact", "catalog")))
                out.append(sentence)
        return out, ids

    if result.tool == "analytical_table":
        table = step.params.get("table")
        if table == "analytical_anomalies":
            rows = report.table("anomalies").rows
            flagged = _number(report, "flagged")
            say("The precomputed anomaly scan flags {} movements across every metric and month (FDR-corrected); the {} largest by score are listed.",
                [(flagged, "", 0), (float(min(5, len(rows))), "", 0)], grade=2)
            for row in rows[:5]:
                kpi, period, dimension_value, delta_pct, direction = row[0], str(row[1])[:7], row[3], row[7], row[8]
                where = f" in {dimension_value}" if dimension_value else ""
                text, rounded = _fmt(delta_pct * 100.0 if delta_pct is not None else None, "%", 1)
                year, month = (float(part) for part in period.split("-"))
                sentence = f"{str(kpi).replace('_', ' ')}{where}, {period}: a {direction} of {text} against expected."
                ids.append(claims.add(sentence, [value for value in (rounded, year, float(int(month))) if value is not None], source, grade=1))
                out.append(sentence)
        elif table == "analytical_forecasts":
            rows = report.table("forecast").rows
            if rows:
                last = rows[-1]
                year, month = (float(part) for part in str(last[2])[:7].split("-"))
                text, value = _fmt(last[3], unit)
                low, low_value = _fmt(last[4], unit)
                high, high_value = _fmt(last[5], unit)
                sentence = f"The {label} forecast for {str(last[2])[:7]} is {text}, with an interval of {low} to {high} ({last[6]} model)."
                ids.append(claims.add(sentence, [v for v in (value, low_value, high_value, year, float(int(month))) if v is not None], source, grade=2))
                out.append(sentence)
                mape = last[8]
                if mape is not None:
                    say("Its backtest MAPE on held-out months is {}.", [(float(mape) * 100, "%", 1)], grade=2)
                else:
                    out.append("It was not backtested because the history was too short.")
        return out, ids

    if result.tool == "sql" and step.purpose.startswith("Monthly "):
        return out, ids  # a supporting series feeds an engine; its rows are evidence, not narrative
    if result.tool == "sql":
        if method == "sql.trend":
            say(f"{label.capitalize()} moved from {{}} to {{}} over the window, a change of {{}}.",
                [(_number(report, "first_value"), unit, 2), (_number(report, "last_value"), unit, 2), (_number(report, "change_pct"), "%", 1)])
            say("The average per period was {}, ranging from {} to {}.",
                [(_number(report, "mean_value"), unit, 2), (_number(report, "min_value"), unit, 2), (_number(report, "max_value"), unit, 2)])
        elif method == "sql.rank":
            rows = report.tables[0].rows if report.tables else ()
            columns = report.tables[0].columns if report.tables else ()
            share_index = columns.index("share") if "share" in columns else None
            for item in report.key_numbers[:3]:
                if item.name.startswith("rank_"):
                    rank = int(item.name.split("_")[1])
                    share = next((row[share_index] for row in rows if share_index is not None and row[-1] == rank), None)
                    if share is not None:
                        say(f"{item.label} ranks {{}} with {{}} ({{}} of the total).", [(float(rank), "", 0), (item.value, unit, 2), (share * 100, "%", 1)])
                    else:
                        say(f"{item.label} ranks {{}} with {{}}.", [(float(rank), "", 0), (item.value, unit, 2)])
            remainder = _number(report, "remainder")
            if remainder is not None:
                say("All remaining values total {}.", [(remainder, unit, 2)])
        elif method == "sql.aggregate":
            for item in report.key_numbers[:6]:
                if item.name.startswith("value:"):
                    pct = next((other.value for other in report.key_numbers if other.name == f"change_pct:{item.label}"), None)
                    if pct is not None:
                        say(f"{label.capitalize()} for {item.label} was {{}} in the current window, a change of {{}} against the comparison window.",
                            [(item.value, unit, 2), (pct, "%", 1)])
                    else:
                        say(f"{label.capitalize()} for {item.label} was {{}}.", [(item.value, unit, 2)])
        else:
            for item in report.key_numbers[:5]:
                if item.name == "value":
                    say(f"{label.capitalize()} for {_period_text(resolved.period if resolved else None)} was {{}}.", [(item.value, unit, 2)])
                elif item.name.startswith("value:"):
                    say(f"{label.capitalize()} for {item.label}: {{}}.", [(item.value, unit, 2)])
        return out, ids

    # Engine outputs
    engine = report.engine
    if engine == "forecast":
        say(f"The {label} forecast for {{}} periods ahead ends at {{}}, with a prediction interval of {{}} to {{}}.",
            [(_number(report, "horizon"), "", 0), (_number(report, "final_yhat"), unit, 2), (_number(report, "final_lower"), unit, 2),
             (_number(report, "final_upper"), unit, 2)], grade=2)
        mape = _number(report, "backtest_mape")
        if mape is not None:
            say(f"The {result.provenance.engine.method if result.provenance.engine else 'model'} backtest MAPE is {{}}.", [(mape * 100, "%", 1)], grade=2)
        arima = _number(report, "arima_backtest_mape")
        if arima is not None:
            say("An ARIMA challenger scored {} on the same held-out months; it is shown for comparison only.", [(arima * 100, "%", 1)], grade=2)
    elif engine == "impact" and "anomaly" in method:
        say(f"{label.capitalize()} was {{}} against an expected {{}}, a deviation of {{}}.",
            [(_number(report, "actual"), unit, 2), (_number(report, "expected"), unit, 2), (_number(report, "deviation_pct"), "%", 1)], grade=2)
        flagged = _number(report, "flagged_periods")
        tested = _number(report, "tested_periods")
        if flagged is not None and tested is not None and tested > 1:
            say("{} of {} periods tested were flagged unusual.", [(flagged, "", 0), (tested, "", 0)], grade=2)
    elif engine == "impact" and step.purpose.startswith("Measure the baseline"):
        say(f"Baseline {label} over the last 3 complete months was {{}}.", [(_number(report, "current"), unit, 2)], grade=1)
    elif engine == "impact":
        say(f"The change in {label} was {{}} ({{}}) against the baseline of {{}}.",
            [(_number(report, "delta"), unit, 2), (_number(report, "delta_pct"), "%", 1), (_number(report, "baseline"), unit, 2)], grade=2)
        p_value = _number(report, "p_value")
        if p_value is not None:
            out.append("The change is statistically significant." if p_value < 0.05 else "The change is not statistically significant.")
        say("The gap to target is {} ({} attainment).", [(_number(report, "gap_to_target"), unit, 2), (_number(report, "target_attainment_pct"), "%", 1)], grade=2)
        say("Against peers the change differs by {} points.", [(_number(report, "excess_vs_peer_pts"), "", 1)], grade=2)
    elif engine == "diagnostic":
        ranked = report.table("ranked_drivers").rows if any(table.name == "ranked_drivers" for table in report.tables) else ()
        say(f"The total change in {label} was {{}}.", [(_number(report, "total_change"), unit, 2)], grade=1, kind="concentration")
        for row in [row for row in ranked if row[1] == "difference_in_differences"][:2]:
            grade = int(row[7])
            verdict = "specific to that group against the comparison group" if grade >= 3 else "not specific to that group"
            say(f"{row[0]}: a difference-in-differences effect of {{}}, {verdict} (evidence grade {{}}).",
                [(row[2], "", 2), (float(grade), "", 0)], grade=min(grade, 3), kind="consistent_with")
        for row in [row for row in ranked if row[1] == "contribution"][:3]:
            note = row[11] if "ratio component" in str(row[11]) else "concentration"
            say(f"{row[0]} accounts for {{}} of the change ({note}).", [(row[2], unit, 2)], grade=1, kind="concentration")
        significant = [row for row in ranked if row[1] == "correlation" and int(row[7]) >= 2]
        for row in significant[:3]:
            say(f"{row[0]} co-moves with {label} (correlation {{}} at a lag of {{}} periods, evidence grade {{}}).",
                [(row[2], "", 2), (float(row[9]), "", 0), (float(row[7]), "", 0)], grade=2, kind="co_movement")
        tested = [row for row in ranked if row[1] == "correlation"]
        if tested and not significant:
            out.append("No candidate driver co-moved significantly once the multiple-testing correction was applied.")
        demoted = [row for row in tested if "reallocation" in str(row[11])]
        for row in demoted[:1]:
            out.append(f"{row[0]} moved in the same window but is a reallocation within an unchanged total, so it is not treated as the driver.")
        if _number(report, "asp_change") is not None:
            say("Average price moved by {}: price effect {}, mix effect {}.",
                [(_number(report, "asp_change"), "", 2), (_number(report, "asp_rate_effect"), "", 2), (_number(report, "asp_mix_effect"), "", 2)])
    elif engine == "scenario":
        say("For a price change of {}, the fitted elasticity is {} (interval {} to {}).",
            [(_number(report, "price_change_pct"), "%", 1), (_number(report, "elasticity"), "", 2), (_number(report, "elasticity_low"), "", 2),
             (_number(report, "elasticity_high"), "", 2)], grade=2, kind="consistent_with")
        say("Demand changes by {} and revenue by {} (Monte Carlo interval {} to {}).",
            [(_number(report, "demand_delta_pct"), "%", 1), (_number(report, "revenue_delta_pct"), "%", 1),
             (_number(report, "revenue_delta_low"), "%", 1), (_number(report, "revenue_delta_high"), "%", 1)], grade=2, kind="consistent_with")
        say("Against the measured baseline revenue of {}, that is {}.", [(_number(report, "baseline_revenue"), "R$", 2), (_number(report, "revenue_delta"), "R$", 2)],
            grade=2, kind="consistent_with")
        out.append("This is an observational estimate on synthetic data, not the result of a price experiment.")
    elif engine == "prescriptive":
        if method == "kmeans":
            clusters = report.table("clusters").rows
            columns = report.table("clusters").columns
            say("Customers fall into {} segments, ranked by measured revenue per customer.", [(float(len(clusters)), "", 0)])
            for rank, row in enumerate(clusters[:3], start=1):
                traits = [name.split("=", 1)[1] for name, value in zip(columns[4:], row[4:], strict=False)
                          if "=" in str(name) and isinstance(value, (int, float)) and value >= 0.5]
                described = f" ({', '.join(traits[:3])})" if traits else ""
                say(f"Segment rank {{}}{described} holds {{}} customers averaging {{}} revenue each.",
                    [(float(rank), "", 0), (float(row[1]), "", 0), (float(row[2]), "R$", 2)])
            if clusters:
                out.append("Target the first-ranked segment first; segments are descriptive groupings, not proof of response to a campaign.")
        elif method == "linprog_highs":
            say("The optimised reorder spends {} of a {} budget and covers {} of forecast demand.",
                [(_number(report, "spend"), "R$", 2), (_number(report, "budget"), "R$", 2), ((_number(report, "fill_rate") or 0) * 100, "%", 1)])
            plan_rows = sorted(report.table("reorder_plan").rows, key=lambda row: -(row[2] or 0))
            for row in [row for row in plan_rows if (row[1] or 0) > 0][:3]:
                say(f"Reorder {{}} units of {row[0]} for {{}}.", [(float(row[1]), "", 1), (float(row[2]), "R$", 2)])
        else:
            for row in report.tables[0].rows[:3] if report.tables else ():
                kind = "information-gathering" if row[3] == "information_gathering" else "intervention"
                say(f"Option {{}} ({kind}): {row[2]}.", [(float(row[0]), "", 0)], grade=1)
    return out, ids


# --------------------------------------------------------------------------- #
# Envelope
# --------------------------------------------------------------------------- #


_LAYER_WORDS = {"real": "a real Olist", "synthetic": "a synthetic (generated, not real business)", "user_supplied": "a user-supplied",
                "analytical": "a derived (engine output)"}


def _catalog_numbers(sentence: str) -> list[float]:
    """Every figure in a catalog sentence: catalog-held counts and dates read by fixed statements (acceptance 1.16)."""
    return [_token_value(match.group(1)) for match in _NUMBER.finditer(sentence)]


def _table_sentences(facts: dict[str, Any], examples: list[str]) -> list[str]:
    """Deterministic sentences describing one table (discovery), one claim each."""
    name = facts.get("table")
    sentences = [f"{name} is {_LAYER_WORDS.get(str(facts.get('layer')), 'a')} table about {facts.get('subject')}, "
                 f"one row per {facts.get('grain')}: {str(facts.get('description', '')).rstrip('.')}."]
    if facts.get("present") != "yes":
        sentences.append(f"{name} is registered in the catalog but is not loaded in this database.")
    else:
        span = f", dated {facts['from']} to {facts['to']}" if facts.get("from") else ""
        sentences.append(f"{name} holds {format_number(float(facts.get('rows') or 0))} rows{span}.")
    if facts.get("columns"):
        sentences.append(f"Its columns are {facts['columns']}; the key is {facts.get('keys')}.")
    if facts.get("metrics"):
        sentences.append(f"Governed metrics built on {name}: {facts['metrics']}.")
    else:
        sentences.append(f"No governed metric is built directly on {name}.")
    if examples:
        sentences.append("You could ask: " + "; ".join(f"\u201c{question}\u201d" for question in examples) + ".")
    return sentences


def _years(*periods) -> list[float]:
    values: list[float] = []
    for period in periods:
        if period is None:
            continue
        for value in (period.start, period.end):
            values.extend([float(value.year), float(value.month)])
    return values


def compose(
    *,
    run_id: str,
    intent: IntentResult,
    resolved: ResolvedQuestion | None,
    plan: Plan | None,
    results: dict[str, ToolResult],
    reports: dict[str, EngineReport],
    queries: list[dict[str, Any]],
    clarification: ClarificationRequest | None,
    catalog_version: str,
    latency_ms: int,
    extra_caveats: tuple[str, ...] = (),
    blocked: BlockBlock | None = None,
    model_used: bool = False,
) -> tuple[AnswerEnvelopeV2, Ledger]:
    claims = Claims()
    narrative: list[str] = []
    step_results: list[StepResultSummary] = []
    evidence: list[EvidenceBlock] = []
    caveats: list[str] = list(extra_caveats)
    assumptions: list[str] = list(resolved.assumptions) if resolved is not None else []
    next_actions: tuple[ActionOption, ...] = ()
    if resolved is not None and (resolved.period or resolved.comparison_period):
        claims.add(f"Scope: {_period_text(resolved.period)}", _years(resolved.period, resolved.comparison_period),
                   ("query", queries[0]["query_id"] if queries else "catalog"))
    if intent.entities.horizon is not None:
        claims.add("Forecast horizon", [float(intent.entities.horizon.periods), *[float(part) for part in intent.entities.horizon.anchor.split("-")]],
                   ("artifact", "horizon"))

    if plan is not None:
        for step in plan.steps:
            result = results.get(step.step_id)
            report = reports.get(step.step_id)
            if result is None:
                step_results.append(StepResultSummary(step_id=step.step_id, tool=step.tool, status="skipped", purpose=step.purpose,
                                                      summary="Not run.", duration_ms=0, reason="The step was not reached."))
                continue
            ids: list[str] = []
            if result.status in ("ok", "empty") and report is not None:
                sentences, ids = _sentences(step, result, report, claims, resolved)
                narrative.extend(sentences)
                for note in report.assumptions:
                    if note and note not in assumptions and len(assumptions) < 40:
                        assumptions.append(note)
            caveats.extend(caveat for caveat in result.caveats if caveat not in caveats)
            if result.analyst_output is not None:
                evidence.append(EvidenceBlock(module=result.analyst_output.module,
                                              output=result.analyst_output.model_dump(mode="json", exclude={"parameters"}), source_claims=tuple(ids)))
                result_payload = result.analyst_output.result
                if result_payload is not None and getattr(result_payload, "mode", None) == "rank_actions" and "prescriptive" in intent.intent_names:
                    next_actions = tuple(result_payload.actions)
            elif result.rows is not None and result.status == "ok":
                evidence.append(EvidenceBlock(module="lookup", output={"query_id": result.rows.query_id, "columns": [c.name for c in result.rows.columns],
                                                                       "rows": [list(row) for row in result.rows.rows[:50]]}, source_claims=tuple(ids)))
            summary = (narrative[-1] if ids and narrative else None) or (result.reason or f"{step.tool} finished with status {result.status}.")
            step_results.append(StepResultSummary(step_id=step.step_id, tool=step.tool, status=result.status, purpose=step.purpose,
                                                  summary=summary[:400], claim_ids=tuple(ids), duration_ms=result.duration_ms,
                                                  reason=result.reason if result.status not in ("ok", "empty") else None))
            if result.status not in ("ok", "empty") and result.reason:
                caveats.append(f"Step {step.step_id} ({step.tool}) {result.status}: {result.reason}")
        for dropped in plan.intents_dropped:
            caveats.append(f"Not answered: the {dropped.intent} part. {dropped.reason}")

    synthetic_tables = sorted({name for result in results.values() for name in result.provenance.synthetic_tables})
    if synthetic_tables:
        from semantic.layers import synthetic_caveat

        caveats = [caveat for caveat in caveats if not caveat.startswith("Based on synthetic data:")]
        caveats.insert(0, synthetic_caveat(synthetic_tables) or "")
    ledger = Ledger(run_id=run_id, claims=tuple(claims.claims))
    narrative = list(dict.fromkeys(narrative))
    text = " ".join(narrative) if narrative else None
    check = FactChecker().verify(text, ledger)
    conclusion = check.repaired_narrative
    ok_steps = [result for result in results.values() if result.status in ("ok", "empty")]
    if blocked is not None:
        status = "blocked"
    elif clarification is not None:
        status = "clarify"
    elif plan is None:
        status = "error"
    elif not ok_steps or not conclusion:
        status = "insufficient_evidence"
    else:
        status = "answered"
    if status == "insufficient_evidence" and not conclusion:
        reasons = [result.reason for result in results.values() if result.reason]
        conclusion = reasons[0] if reasons else "The plan produced no evidence-backed figure."
    diagnostic = "diagnostic" in intent.intent_names
    route = RouteSummary(labels=intent.route_labels, confidence=intent.confidence, reason=intent.reason)
    scope = EnvelopeScope(metric=resolved.metric_id if resolved else None, window=_period_text(resolved.period) if resolved and resolved.period else None,
                          filters=tuple(f"{item.dimension} {item.operator} {', '.join(item.values)}" for item in (resolved.filters if resolved else ())),
                          grain=resolved.grain if resolved else None, governed=bool(resolved and resolved.metric_id))
    envelope = AnswerEnvelopeV2(
        run_id=run_id,
        status=status,  # type: ignore[arg-type]
        route=route,
        conclusion=conclusion if status in ("answered", "insufficient_evidence") else None,
        scope=scope,
        evidence=tuple(evidence),
        claims=ledger.claims,
        method=tuple(MethodStep(name=f"{step.step_id}:{step.tool}", params={"purpose": step.purpose}) for step in plan.steps) if plan else (),
        queries=tuple(EnvelopeQueryRecord(query_id=item["query_id"], sql=item["sql"], status=item["status"], duration_ms=int(item["duration_ms"]),
                                          origin="compiler", validation_mode="enterprise") for item in queries),
        caveats=tuple(dict.fromkeys(caveats)),
        causal_boundary_note=CAUSAL_BOUNDARY if diagnostic else None,
        next_actions=next_actions,
        clarification=clarification,
        refusal=None if status != "refused" else RefusalBlock(missing=()),
        block=blocked,
        run_metrics=RunMetrics(latency_ms=max(0, latency_ms), tokens=0, queries=len(queries),
                               rows=sum(int(item.get("rows", 0) or 0) for item in queries), retries=0),
        provenance=Provenance(model_name="ollama" if model_used else "none", snapshot_id="brazil-ecommerce", catalog_version=catalog_version,
                              timestamp=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")),
        resolved_question=resolved,
        intent=intent,
        plan=plan,
        step_results=tuple(step_results),
        assumptions=tuple(dict.fromkeys(assumptions)),
        follow_ups=_follow_ups(intent, resolved),
        visualizations=build_visualizations(plan.steps if plan else (), results,
                                             {item.step_id: item.claim_ids for item in step_results}),
    )
    return envelope, ledger


def _follow_ups(intent: IntentResult, resolved: ResolvedQuestion | None) -> tuple[FollowUpSuggestion, ...]:
    if resolved is None or resolved.metric_id is None:
        return ()
    label = resolved.metric_id.replace("_", " ")
    names = intent.intent_names
    suggestions = []
    if "forecast" not in names:
        suggestions.append(FollowUpSuggestion(text=f"Forecast {label} for the next 3 months", intent="forecast",
                                              rationale="Extends the measured series forward with an interval."))
    if "diagnostic" not in names:
        suggestions.append(FollowUpSuggestion(text=f"Why did {label} change last month?", intent="diagnostic",
                                              rationale="Attributes the latest change across dimensions."))
    return tuple(suggestions[:2])


__all__ = ["Claims", "compose"]
