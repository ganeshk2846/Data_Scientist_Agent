"""End-to-end V2 evaluation against a live backend (build-plan-v2 G6/G8, EVAL-2..7).

Every question goes over HTTP to ``POST /api/v2/ask`` and the finished
``AnswerEnvelopeV2`` is read back from ``GET /api/v2/runs/{run_id}``; nothing
is mocked and no backend module is imported to answer a question. The only
backend import is the frozen V1 contract, used to check that ``/api/ask`` still
returns the V1 envelope shape.

Expectations live in ``scripts/eval_v2_bank.yaml`` and
``scripts/eval_v2_multiturn.yaml`` (written from spec/v2/scope.md), key numbers
are recomputed by reference SQL on a read-only connection, and planted effects
are scored against ``data/SYNTHETIC_GROUND_TRUTH.md``.

Every case lands in exactly one category:

    correct                expected outcome, intent and every check/number/plant
    routing_failure        wrong outcome class (answer/clarify/refuse) or wrong intent
    execution_failure      HTTP error, timeout, status error/blocked
    insufficient_evidence  routed correctly but the run returned insufficient_evidence
    incorrect_answer       routed and answered, but a key number, check or plant failed

Latency is the client wall clock from sending ``POST /api/v2/ask`` to receiving
the complete envelope (the GET long-polls server side, so no polling interval
is added), measured sequentially, one request at a time, after one discarded
warm-up question. The server's own ``run_metrics.latency_ms`` is reported beside it.

Usage (from the repository root)::

    python scripts/eval_v2.py --serve                 # start uvicorn on the V2 build, run, stop
    python scripts/eval_v2.py --base-url http://127.0.0.1:8000 --token $DS_AGENT_TOKEN
    python scripts/eval_v2.py --serve --save-json docs/eval_v2/final.json --baseline docs/eval_v2/baseline.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import socket
import sqlite3
import statistics
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "scripts" / "eval_v2_bank.yaml"
MULTITURN = ROOT / "scripts" / "eval_v2_multiturn.yaml"
GROUND_TRUTH = ROOT / "data" / "SYNTHETIC_GROUND_TRUTH.md"
DEFAULT_DB = ROOT / "data" / "brazil_ecommerce_v2.sqlite"
REPORT = ROOT / "docs" / "EVAL_V2.md"
BEGIN, END = "<!-- BEGIN GENERATED: scripts/eval_v2.py -->", "<!-- END GENERATED: scripts/eval_v2.py -->"

CATEGORIES = ("correct", "routing_failure", "execution_failure", "insufficient_evidence", "incorrect_answer")
SECTIONS = {
    "D": "discovery", "C": "clarify", "S": "descriptive", "G": "diagnostic", "E-G": "diagnostic",
    "I": "impact", "F": "forecast", "X": "scenario", "P": "prescriptive", "K": "compound", "V": "vague",
    "R-": "v1_regression",
}
SECTION_ORDER = ("discovery", "clarify", "descriptive", "diagnostic", "impact", "forecast", "scenario",
                 "prescriptive", "compound", "vague", "v1_regression")
OUTCOME_OF_STATUS = {"answered": "answer", "clarify": "clarify", "refused": "refuse",
                     "insufficient_evidence": "answer", "error": "error", "blocked": "error"}
V1_EVENTS = {"step_started", "step_finished", "clarify", "answer", "error"}
CAUSAL = re.compile(r"\b(caused|causes|because of|due to|led to|resulted in|drove the)\b", re.IGNORECASE)
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


# ----------------------------------------------------------------- transport
class Client:
    def __init__(self, base_url: str, token: str | None, timeout: float) -> None:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.http = httpx.Client(base_url=base_url, headers=headers, timeout=30.0)
        self.timeout = timeout

    def ask(self, question: str, session_id: str, **extra: Any) -> dict[str, Any]:
        """One timed V2 round trip; never raises."""
        started = time.perf_counter()
        try:
            response = self.http.post("/api/v2/ask", json={"question": question, "session_id": session_id, **extra})
            if response.status_code != 200:
                return {"error": f"POST /api/v2/ask -> HTTP {response.status_code}: {response.text[:200]}",
                        "latency_ms": _ms(started)}
            run_id = response.json()["run_id"]
            while True:
                got = self.http.get(f"/api/v2/runs/{run_id}")
                if got.status_code == 200:
                    envelope = got.json()
                    return {"run_id": run_id, "envelope": envelope, "latency_ms": _ms(started),
                            "stream": self.stream_check(run_id)}
                if got.status_code != 202:
                    return {"run_id": run_id, "error": f"GET run -> HTTP {got.status_code}", "latency_ms": _ms(started)}
                if time.perf_counter() - started > self.timeout:
                    return {"run_id": run_id, "error": f"timeout after {self.timeout:.0f}s", "latency_ms": _ms(started)}
        except httpx.HTTPError as exc:
            return {"error": f"{type(exc).__name__}: {exc}", "latency_ms": _ms(started)}

    def stream_check(self, run_id: str) -> dict[str, Any]:
        """Replay the SSE stream (V1 transport) and check its event names and terminal event."""
        names: list[str] = []
        try:
            with self.http.stream("GET", f"/api/runs/{run_id}/events", timeout=20.0) as stream:
                for line in stream.iter_lines():
                    if line.startswith("event:"):
                        names.append(line.split(":", 1)[1].strip())
                        if names[-1] in ("answer", "error"):
                            break
        except httpx.HTTPError as exc:
            return {"ok": False, "reason": f"{type(exc).__name__}", "events": names}
        unknown = sorted(set(names) - V1_EVENTS - {"stage", "progress"})
        terminal = bool(names) and names[-1] in ("answer", "error")
        return {"ok": terminal, "events": sorted(set(names)), "unknown": unknown}


def _ms(started: float) -> int:
    return int(round((time.perf_counter() - started) * 1000))


# ------------------------------------------------------------- ground truth
def load_ground_truth(path: Path) -> dict[str, list[dict[str, str]]]:
    """Parse the fact tables of SYNTHETIC_GROUND_TRUTH.md, grouped by plant (E1..E5)."""
    plants: dict[str, list[dict[str, str]]] = defaultdict(list)
    header: list[str] | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            header = None if not line.strip() else header
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] == "Fact":
            header = cells
            continue
        if header is None or set(cells[0]) <= {"-", " "}:
            continue
        row = dict(zip(header, cells))
        fact = row["Fact"].strip("`")
        row["Fact"] = fact
        plants[fact.split("-", 1)[0]].append(row)
    return dict(plants)


def check_plant_tokens(plants_cfg: dict[str, Any], truth: dict[str, list[dict[str, str]]]) -> list[str]:
    """The bank's plant tokens must still name every cause table in the answer key."""
    problems = []
    for plant, rows in truth.items():
        tokens = [token.lower() for token in plants_cfg.get(plant, {}).get("cause", [])]
        if plant not in plants_cfg:
            problems.append(f"{plant} is in the answer key but not in the bank")
            continue
        for row in rows:
            if row.get("Cause?") == "yes":
                table = row["Table.column"].strip("`").split(".")[0]
                if not any(table.startswith(token) or token.startswith(table) for token in tokens):
                    problems.append(f"{plant}: cause table {table} has no token in the bank")
    return problems


# -------------------------------------------------------------- reference SQL
class Reference:
    def __init__(self, db: Path) -> None:
        self.conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    def scalar(self, sql: str) -> float | None:
        row = self.conn.execute(sql).fetchone()
        return None if row is None or row[0] is None else float(row[0])


def envelope_numbers(envelope: dict[str, Any]) -> list[float]:
    values = [number["value"] for claim in envelope.get("claims", ()) for number in claim.get("numbers", ())]
    for match in NUMBER.findall(envelope.get("conclusion") or ""):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            pass
    return values


def number_present(expected: float, values: list[float]) -> bool:
    tolerance = max(abs(expected) * 0.005, 0.006)
    return any(abs(value - expected) <= tolerance or abs(value - expected * 100) <= tolerance * 100 for value in values)


# --------------------------------------------------------------------- checks
def _texts(envelope: dict[str, Any]) -> str:
    parts = [envelope.get("conclusion") or ""]
    parts += [claim.get("text", "") for claim in envelope.get("claims", ())]
    return "\n".join(parts)


def _all_text(envelope: dict[str, Any]) -> str:
    return json.dumps({key: envelope.get(key) for key in ("conclusion", "caveats", "scope", "claims", "clarification",
                                                           "refusal", "assumptions")}).lower()


def check(name: str, envelope: dict[str, Any]) -> str | None:
    """Return a failure reason, or None when the check passes."""
    if name == "names_synthetic":
        return None if "synthetic" in _all_text(envelope) else "answer reads synthetic data but never says so (V2-SYN-4)"
    if name == "names_missing_age_gender":
        text = _all_text(envelope)
        return None if "age" in text and "gender" in text else "does not name the missing attributes (ABS-1)"
    if name == "no_causal_claim":
        hit = CAUSAL.search(_texts(envelope))
        return None if hit is None else f"causal wording {hit.group(0)!r} without a grade-4 method (DRV-9)"
    if name == "anchor_2018_08":
        horizon = ((envelope.get("intent") or {}).get("entities") or {}).get("horizon") or {}
        return None if horizon.get("anchor") == "2018-08" else f"forecast anchor {horizon.get('anchor')!r} != '2018-08' (V2-DATA-2)"
    if name == "has_interval":
        ok = "interval" in _texts(envelope).lower() or any(v.get("kind") == "forecast_fan" for v in envelope.get("visualizations", ()))
        return None if ok else "forecast without an interval"
    if name == "has_options":
        count = len(envelope.get("next_actions", ()))
        return None if count >= 2 else f"{count} ranked options, scope.md 3.8 requires 2-3 (REC-3)"
    raise KeyError(f"unknown check {name!r}")


def plant_result(plant: str, cfg: dict[str, Any], envelope: dict[str, Any]) -> dict[str, Any]:
    text = _texts(envelope).lower()
    cause = [token for token in cfg["cause"] if token.lower() in text]
    driver_claims = " ".join(claim.get("text", "") for claim in envelope.get("claims", ())
                             if claim.get("kind") in ("co_movement", "consistent_with", "hypothesis")).lower()
    confounder = [token for token in cfg["confounder"] if token.lower() in driver_claims]
    return {"plant": plant, "recovered": bool(cause), "cause_tokens": cause,
            "misattributed": bool(confounder) and not cause, "confounder_tokens": confounder}


# -------------------------------------------------------------------- scoring
def intents_of(envelope: dict[str, Any]) -> list[str]:
    return [item["intent"] for item in ((envelope.get("intent") or {}).get("intents") or ())]


def section_of(case_id: str) -> str:
    for prefix in sorted(SECTIONS, key=len, reverse=True):
        if case_id.startswith(prefix) and (len(prefix) > 1 or case_id[1:].isdigit()):
            return SECTIONS[prefix]
    return "other"


def score_case(case: dict[str, Any], result: dict[str, Any], reference: Reference,
               plants_cfg: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": case["id"], "question": case["question"], "section": section_of(case["id"]),
        "expected_intent": case["intent"], "expected_outcome": case["outcome"], "layer": case.get("layer", "-"),
        "must_answer": bool(case.get("must_answer")), "latency_ms": result.get("latency_ms"), "reasons": [],
        "plant_expected": case.get("plant"),
    }
    if "error" in result:
        row.update(category="execution_failure", status="http_error", intents=[], has_chart=False)
        row["reasons"].append(result["error"])
        return row
    envelope = result["envelope"]
    status = envelope.get("status")
    intents = intents_of(envelope)
    row.update(status=status, intents=intents, has_chart=bool(envelope.get("visualizations")),
               server_latency_ms=(envelope.get("run_metrics") or {}).get("latency_ms"),
               steps=[f"{step['tool']}:{step['status']}" for step in envelope.get("step_results", ())],
               stream_ok=result.get("stream", {}).get("ok"), conclusion=(envelope.get("conclusion") or "")[:300])
    outcome = OUTCOME_OF_STATUS.get(status, "error")

    if outcome == "error":
        row["category"] = "execution_failure"
        row["reasons"].append(f"status {status}: {'; '.join(envelope.get('caveats', ())[:1])}")
        return row
    if outcome != case["outcome"]:
        row["category"] = "routing_failure"
        detail = ""
        if status == "clarify" and envelope.get("clarification"):
            detail = f" (asked: {envelope['clarification'].get('question')!r})"
        row["reasons"].append(f"expected {case['outcome']}, got {status}{detail}")
        return row
    if case["outcome"] == "answer":
        wanted = case.get("intents") or [case["intent"]]
        if intents[:1] != [case["intent"]] or not set(wanted) <= set(intents):
            row["category"] = "routing_failure"
            row["reasons"].append(f"expected intents {wanted} (primary {case['intent']}), got {intents}")
            return row
        if status == "insufficient_evidence":
            row["category"] = "insufficient_evidence"
            row["reasons"].append((envelope.get("conclusion") or "; ".join(envelope.get("caveats", ())))[:200])
            return row

    failures: list[str] = []
    for name in case.get("checks", ()):
        reason = check(name, envelope)
        if reason:
            failures.append(reason)
    if case.get("key_sql"):
        options = case["key_sql"] if isinstance(case["key_sql"], list) else [case["key_sql"]]
        expected = [value for value in (reference.scalar(sql) for sql in options) if value is not None]
        numbers = envelope_numbers(envelope)
        row["key_numbers"] = expected
        if not any(number_present(value, numbers) for value in expected):
            failures.append(f"key number {', '.join(f'{v:,.2f}' for v in expected)} (reference SQL) not in the answer")
    if case.get("plant"):
        plant = plant_result(case["plant"], plants_cfg[case["plant"]], envelope)
        row["plant"] = plant
        if not plant["recovered"]:
            failures.append(f"planted {case['plant']} cause not identified")
        if plant["misattributed"]:
            failures.append(f"{case['plant']} confounder reported as the driver: {plant['confounder_tokens']}")
    row["category"] = "incorrect_answer" if failures else "correct"
    row["reasons"] += failures
    return row


def _period_label(period: dict[str, str] | None) -> str | None:
    if not period:
        return None
    start = dt.date.fromisoformat(period["start"])
    end = dt.date.fromisoformat(period["end"]) - dt.timedelta(days=1)
    return f"{start:%Y-%m}..{end:%Y-%m}"


def score_turn(expect: dict[str, Any], result: dict[str, Any]) -> tuple[str, list[str]]:
    if "error" in result:
        return "execution_failure", [result["error"]]
    envelope = result["envelope"]
    status = envelope.get("status")
    outcome = OUTCOME_OF_STATUS.get(status, "error")
    if outcome == "error":
        return "execution_failure", [f"status {status}"]
    allowed = expect["outcome"] if isinstance(expect["outcome"], list) else [expect["outcome"]]
    if outcome not in allowed:
        return "routing_failure", [f"expected {allowed}, got {status}"]
    intents = intents_of(envelope)
    if "intent" in expect and outcome == "answer":
        wanted = expect["intent"] if isinstance(expect["intent"], list) else [expect["intent"]]
        if intents[:1] and intents[0] not in wanted:
            return "routing_failure", [f"expected intent {wanted}, got {intents}"]
    if status == "insufficient_evidence" and "answer" in allowed:
        return "insufficient_evidence", [(envelope.get("conclusion") or "")[:200]]
    failures = []
    resolved = envelope.get("resolved_question") or {}
    if outcome == "answer":
        if "metric" in expect and resolved.get("metric_id") != expect["metric"]:
            failures.append(f"metric {resolved.get('metric_id')!r} != {expect['metric']!r}")
        got_filters = {item["dimension"]: sorted(item["values"]) for item in resolved.get("filters", ())}
        for dimension, values in (expect.get("filters") or {}).items():
            if got_filters.get(dimension) != sorted(values):
                failures.append(f"filter {dimension}={got_filters.get(dimension)} != {values}")
        if expect.get("no_filters") and got_filters:
            failures.append(f"unexpected filters {got_filters}")
        if "period" in expect and _period_label(resolved.get("period")) != expect["period"]:
            failures.append(f"period {_period_label(resolved.get('period'))} != {expect['period']}")
        for dimension in expect.get("dimensions", ()):
            if dimension not in resolved.get("dimensions", ()):
                failures.append(f"dimension {dimension} not resolved (got {resolved.get('dimensions')})")
        if expect.get("inherits") and not resolved.get("inherited_fields"):
            failures.append("nothing shown as inherited from the previous turn (scope.md 6.3 rule 2)")
    return ("incorrect_answer" if failures else "correct"), failures


# --------------------------------------------------------------------- runners
def run_bank(client: Client, cases: list[dict[str, Any]], reference: Reference, plants_cfg: dict[str, Any],
             tag: str) -> list[dict[str, Any]]:
    rows = []
    for index, case in enumerate(cases, 1):
        result = client.ask(case["question"], session_id=f"eval-{tag}-{case['id']}")
        row = score_case(case, result, reference, plants_cfg)
        rows.append(row)
        print(f"[{index:3}/{len(cases)}] {case['id']:7} {row['category']:22} {row.get('status', ''):22} "
              f"{row['latency_ms']:>6} ms  {'; '.join(row['reasons'])[:110]}", flush=True)
    return rows


def run_scripts(client: Client, scripts: list[dict[str, Any]], tag: str) -> list[dict[str, Any]]:
    out = []
    for script in scripts:
        session = f"eval-{tag}-mt-{script['id']}"
        previous: dict[str, Any] | None = None
        turns = []
        for number, turn in enumerate(script["turns"], 1):
            extra: dict[str, Any] = {}
            if turn.get("reply") and previous and "envelope" in previous:
                clarification = previous["envelope"].get("clarification") or {}
                extra["clarification_of"] = previous["run_id"]
                if turn["reply"] == "first" and clarification.get("options"):
                    extra["option_id"] = clarification["options"][0]["option_id"]
                elif turn["reply"] == "default" and clarification.get("default_assumption"):
                    extra["option_id"] = clarification["default_assumption"]["option_id"]
            result = client.ask(turn["q"], session_id=session, **extra)
            category, reasons = score_turn(turn["expect"], result)
            envelope = result.get("envelope") or {}
            turns.append({"turn": number, "q": turn["q"], "category": category, "reasons": reasons,
                          "status": envelope.get("status", "http_error"), "intents": intents_of(envelope),
                          "latency_ms": result.get("latency_ms"), "has_chart": bool(envelope.get("visualizations")),
                          "must_answer": number in script.get("must_answer_turns", ()),
                          "inherited": (envelope.get("resolved_question") or {}).get("inherited_fields", [])})
            previous = result
        passed = all(turn["category"] == "correct" for turn in turns)
        out.append({"id": script["id"], "ref": script.get("ref", ""), "passed": passed, "turns": turns})
        print(f"[mt] {script['id']:18} {'PASS' if passed else 'FAIL'}  "
              + " | ".join(f"{t['turn']}:{t['category']}" for t in turns), flush=True)
    return out


def run_v1_regression(client: Client) -> list[dict[str, Any]]:
    """V1 /api/ask still answers with the frozen AnswerEnvelope shape and the V1 SSE event names."""
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    from contracts.models import AnswerEnvelope  # frozen V1 contract; validation only

    rows = []
    for question in ("How many orders were there in August 2018?", "How did revenue in 2018 compare to 2017?",
                     "Was order count unusual in August 2018?"):
        started = time.perf_counter()
        row: dict[str, Any] = {"question": question}
        try:
            response = client.http.post("/api/ask", json={"question": question, "session_id": "eval-v1"})
            run_id = response.json()["run_id"]
            stream = client.stream_check(run_id)
            envelope = client.http.get(f"/api/runs/{run_id}").json()
            AnswerEnvelope.model_validate(envelope)
            row.update(ok=stream["ok"] and not stream.get("unknown"), status=envelope["status"],
                       events=stream["events"], latency_ms=_ms(started),
                       keys_match=set(envelope) == set(AnswerEnvelope.model_fields))
        except Exception as exc:  # recorded, never raised
            row.update(ok=False, status="error", events=[], latency_ms=_ms(started), keys_match=False,
                       error=f"{type(exc).__name__}: {exc}"[:200])
        rows.append(row)
    return rows


# --------------------------------------------------------------------- serving
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def serve(db: Path, token: str) -> tuple[subprocess.Popen, str]:
    port = _free_port()
    env = {**os.environ, "DS_AGENT_DB": str(db), "DS_AGENT_TOKEN": token}
    env.pop("DS_AGENT_API_TOKENS", None)
    process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app:app", "--app-dir", "src", "--port", str(port),
                                "--log-level", "warning"], cwd=ROOT / "backend", env=env)
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(base + "/openapi.json", timeout=1.0).status_code == 200:
                return process, base
        except httpx.HTTPError:
            pass
        if process.poll() is not None:
            raise SystemExit("uvicorn exited before it was ready")
        time.sleep(0.5)
    process.terminate()
    raise SystemExit("uvicorn did not become ready")


def ollama_available() -> bool:
    try:
        return httpx.get("http://127.0.0.1:11434/api/tags", timeout=1.0).status_code == 200
    except httpx.HTTPError:
        return False


def database_facts(db: Path) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    sidecar = db.parent / "synthetic_ground_truth.json"
    snapshot = json.loads(sidecar.read_text())["snapshot_id"] if sidecar.exists() else None
    digest = hashlib.sha256(db.read_bytes()).hexdigest()
    return {"path": str(db.relative_to(ROOT) if db.is_relative_to(ROOT) else db), "orders": orders,
            "real_olist": orders == 99_441, "snapshot_id": snapshot, "sha256": digest}


# --------------------------------------------------------------------- report
def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({part / whole:.0%})" if whole else "0/0 (-)"


def _lat(values: list[int]) -> str:
    values = sorted(v for v in values if v is not None)
    if not values:
        return "-"
    p95 = values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]
    return f"{int(statistics.median(values))} / {p95} / {values[-1]}"


def summarise(rows, scripts, v1) -> dict[str, Any]:
    turns = [turn for script in scripts for turn in script["turns"]]
    must = [row for row in rows if row["must_answer"]] + [turn for turn in turns if turn["must_answer"]]
    return {
        "cases": len(rows), "correct": sum(row["category"] == "correct" for row in rows),
        "categories": dict(Counter(row["category"] for row in rows)),
        "scripts": len(scripts), "scripts_passed": sum(script["passed"] for script in scripts),
        "turns": len(turns), "turns_correct": sum(turn["category"] == "correct" for turn in turns),
        "must_answer": len(must),
        "must_answer_answered": sum((row.get("status") == "answered") for row in must),
        "v1_ok": sum(bool(item.get("ok")) and item.get("keys_match") for item in v1), "v1": len(v1),
    }


def render(run: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    rows, scripts, v1, meta = run["rows"], run["scripts"], run["v1"], run["meta"]
    summary = summarise(rows, scripts, v1)
    lines = [BEGIN, "", f"## Results - {meta['label']}", ""]
    db = meta["database"]
    lines += [
        f"- Run at {meta['started']} UTC on commit `{meta['commit']}`; {meta['duration_s']:.0f} s wall clock.",
        f"- Backend: live uvicorn, `POST /api/v2/ask` + `GET /api/v2/runs/{{id}}` ({meta['base_url']}).",
        f"- Database: `{db['path']}` - {db['orders']:,} orders, sha256 `{db['sha256'][:16]}...`, snapshot "
        f"`{db['snapshot_id']}` - **{'real Olist snapshot + synthetic layer' if db['real_olist'] else 'seeded Olist-shaped FIXTURE + synthetic layer (not the real Olist data)'}**.",
        f"- Local model (Ollama): {'available' if meta['ollama'] else '**unavailable** - every run used the deterministic fallbacks'}.",
        "- Latency: client wall clock from sending the POST to receiving the complete envelope, sequential, "
        "one warm-up question discarded; columns are p50 / p95 / max in ms. Server latency is `run_metrics.latency_ms`.",
        "",
    ]
    if baseline is not None:
        before = summarise(baseline["rows"], baseline["scripts"], baseline["v1"])
        lines += ["### Before / after", "", "| Measure | Baseline | This run |", "| --- | --- | --- |"]
        for label, key, whole in (("Single-turn cases correct", "correct", "cases"),
                                  ("Multi-turn scripts passed", "scripts_passed", "scripts"),
                                  ("Multi-turn turns correct", "turns_correct", "turns"),
                                  ("Must-answer returned `answered`", "must_answer_answered", "must_answer"),
                                  ("V1 regression questions with the V1 shape", "v1_ok", "v1")):
            lines.append(f"| {label} | {_pct(before[key], before[whole])} | {_pct(summary[key], summary[whole])} |")
        for category in CATEGORIES[1:]:
            lines.append(f"| {category} (single-turn) | {before['categories'].get(category, 0)} | {summary['categories'].get(category, 0)} |")
        lines.append("")

    lines += ["### Summary", "", "| Measure | Result |", "| --- | --- |",
              f"| Single-turn cases correct | {_pct(summary['correct'], summary['cases'])} |",
              f"| Multi-turn scripts fully correct | {_pct(summary['scripts_passed'], summary['scripts'])} |",
              f"| Multi-turn turns correct | {_pct(summary['turns_correct'], summary['turns'])} |",
              f"| Must-answer (scope.md 7) returned `answered` | {_pct(summary['must_answer_answered'], summary['must_answer'])} |",
              f"| V1 `/api/ask` regression (V1 envelope shape + V1 SSE names) | {_pct(summary['v1_ok'], summary['v1'])} |",
              "", "### Per intent (single-turn)", "",
              "Denominators are cases in the section. *Routed* = expected outcome class and intent. "
              "*Answered* = status `answered`. *Chart* is over answered cases. *Clarified* = status `clarify` "
              "(expected for the clarify and vague sections).", "",
              "| Section | Cases | Correct | Routed | Answered | Chart (of answered) | Clarified | Latency p50/p95/max ms | Server p50 ms |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_section[row["section"]].append(row)
    for section in SECTION_ORDER:
        group = by_section.get(section, [])
        if not group:
            continue
        n = len(group)
        routed = sum(row["category"] not in ("routing_failure", "execution_failure") for row in group)
        answered = [row for row in group if row.get("status") == "answered"]
        server = [row.get("server_latency_ms") for row in group if row.get("server_latency_ms") is not None]
        lines.append(f"| {section} | {n} | {_pct(sum(r['category'] == 'correct' for r in group), n)} | {_pct(routed, n)} | "
                     f"{_pct(len(answered), n)} | {_pct(sum(r['has_chart'] for r in answered), len(answered))} | "
                     f"{_pct(sum(r.get('status') == 'clarify' for r in group), n)} | {_lat([r['latency_ms'] for r in group])} | "
                     f"{int(statistics.median(server)) if server else '-'} |")
    lines.append(f"| **all** | {len(rows)} | {_pct(summary['correct'], len(rows))} | "
                 f"{_pct(sum(r['category'] not in ('routing_failure', 'execution_failure') for r in rows), len(rows))} | "
                 f"{_pct(sum(r.get('status') == 'answered' for r in rows), len(rows))} | "
                 f"{_pct(sum(r['has_chart'] for r in rows if r.get('status') == 'answered'), sum(r.get('status') == 'answered' for r in rows))} | "
                 f"{_pct(sum(r.get('status') == 'clarify' for r in rows), len(rows))} | {_lat([r['latency_ms'] for r in rows])} | |")

    lines += ["", "### Failure taxonomy (single-turn)", "", "| Section | " + " | ".join(CATEGORIES) + " |",
              "| --- |" + " --- |" * len(CATEGORIES)]
    for section in SECTION_ORDER:
        group = by_section.get(section, [])
        if group:
            counts = Counter(row["category"] for row in group)
            lines.append(f"| {section} | " + " | ".join(str(counts.get(c, 0)) for c in CATEGORIES) + " |")
    totals = Counter(row["category"] for row in rows)
    lines.append("| **all** | " + " | ".join(str(totals.get(c, 0)) for c in CATEGORIES) + " |")

    lines += ["", "### Must-answer gate (V2-ANS-2)", "", "| Ref | Question | Status | Category |", "| --- | --- | --- | --- |"]
    for row in rows:
        if row["must_answer"]:
            lines.append(f"| {row['id']} | {row['question']} | {row.get('status')} | {row['category']} |")
    for script in scripts:
        for turn in script["turns"]:
            if turn["must_answer"]:
                lines.append(f"| {script['id']} turn {turn['turn']} | {turn['q']} (follow-up) | {turn['status']} | {turn['category']} |")

    lines += ["", "### Planted effects (data/SYNTHETIC_GROUND_TRUTH.md)", "",
              "A diagnostic answer *recovers* a plant when its conclusion or a claim names the planted cause; it "
              "*misattributes* when a co-movement claim names the planted confounder instead. Every row reads "
              "synthetic tables, so these are results on generated data only.", "",
              "| Ref | Plant | Question | Status | Recovered | Confounder as driver | Cause tokens found |",
              "| --- | --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        plant = row.get("plant")
        if plant is not None:
            lines.append(f"| {row['id']} | {plant['plant']} | {row['question']} | {row.get('status')} | "
                         f"{'yes' if plant['recovered'] else 'no'} | {'yes' if plant['misattributed'] else 'no'} | "
                         f"{', '.join(plant['cause_tokens']) or '-'} |")
        elif row.get("plant_expected"):
            lines.append(f"| {row['id']} | {row['plant_expected']} | {row['question']} | {row.get('status')} | "
                         f"no ({row['category']}) | - | - |")

    lines += ["", "### Multi-turn scripts", "", "| Script | Spec | Turns correct | Result | Failing turn: reason |",
              "| --- | --- | --- | --- | --- |"]
    for script in scripts:
        good = sum(turn["category"] == "correct" for turn in script["turns"])
        bad = [f"{t['turn']} `{t['q']}`: {t['category']} - {'; '.join(t['reasons'])[:140]}" for t in script["turns"] if t["category"] != "correct"]
        lines.append(f"| {script['id']} | {script['ref']} | {good}/{len(script['turns'])} | {'pass' if script['passed'] else 'FAIL'} | {'<br>'.join(bad) or '-'} |")
    turn_cats = Counter(turn["category"] for script in scripts for turn in script["turns"])
    lines += ["", "Turn categories: " + ", ".join(f"{c} {turn_cats.get(c, 0)}" for c in CATEGORIES) +
              f"; turn latency p50/p95/max {_lat([t['latency_ms'] for s in scripts for t in s['turns']])} ms.", ""]

    lines += ["### V1 regression (`POST /api/ask`)", "", "| Question | Status | SSE events | V1 envelope keys | Latency ms |",
              "| --- | --- | --- | --- | --- |"]
    for item in v1:
        lines.append(f"| {item['question']} | {item['status']} | {', '.join(item['events'])} | "
                     f"{'match' if item.get('keys_match') else 'MISMATCH'} | {item['latency_ms']} |")

    lines += ["", "### Every single-turn case", "", "| Ref | Expected | Got | Category | Latency ms | Reason |",
              "| --- | --- | --- | --- | --- | --- |"]
    for row in rows:
        expected = f"{row['expected_outcome']}/{row['expected_intent']}"
        got = f"{row.get('status')}/{','.join(row.get('intents', [])) or '-'}"
        reason = "; ".join(row["reasons"]).replace("|", "/")[:220] or "-"
        lines.append(f"| {row['id']} | {expected} | {got} | {row['category']} | {row['latency_ms']} | {reason} |")
    lines += ["", END]
    return "\n".join(lines)


def write_report(path: Path, generated: str) -> None:
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if BEGIN in text and END in text:
            head, rest = text.split(BEGIN, 1)
            tail = rest.split(END, 1)[1]
            path.write_text(head + generated + tail, encoding="utf-8")
            return
    path.write_text("# V2 evaluation\n\n" + generated + "\n", encoding="utf-8")


# ------------------------------------------------------------------------ main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=os.environ.get("DS_AGENT_URL"))
    parser.add_argument("--token", default=os.environ.get("DS_AGENT_TOKEN"))
    parser.add_argument("--serve", action="store_true", help="start uvicorn on --db for the run and stop it after")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("DS_AGENT_DB") or DEFAULT_DB))
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--save-json", type=Path)
    parser.add_argument("--baseline", type=Path, help="results JSON of an earlier run, shown as before/after")
    parser.add_argument("--label", default="current")
    parser.add_argument("--only", help="comma-separated case/script ids")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args(argv)

    db = args.db.resolve()
    if not db.exists():
        raise SystemExit(f"{db} not found - build it with `python scripts/build_v2.py` first")
    bank = yaml.safe_load(BANK.read_text(encoding="utf-8"))
    scripts = yaml.safe_load(MULTITURN.read_text(encoding="utf-8"))["scripts"]
    cases = bank["cases"]
    truth = load_ground_truth(GROUND_TRUTH)
    problems = check_plant_tokens(bank["plants"], truth)
    if problems:
        raise SystemExit("bank plants out of step with the answer key: " + "; ".join(problems))
    if args.only:
        wanted = set(args.only.split(","))
        cases = [case for case in cases if case["id"] in wanted]
        scripts = [script for script in scripts if script["id"] in wanted]

    process = None
    token = args.token
    base_url = args.base_url
    if args.serve:
        token = token or secrets.token_hex(24)
        process, base_url = serve(db, token)
    if not base_url:
        raise SystemExit("pass --base-url or --serve")
    started = time.perf_counter()
    started_at = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        client = Client(base_url, token, args.timeout)
        client.ask("What data do you have?", session_id="eval-warmup")  # warm-up, discarded
        tag = secrets.token_hex(3)
        rows = run_bank(client, cases, Reference(db), bank["plants"], tag)
        script_rows = run_scripts(client, scripts, tag)
        v1 = run_v1_regression(client)
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=20)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    run = {"meta": {"label": args.label, "started": started_at, "commit": commit + ("+dirty" if dirty else ""),
                    "duration_s": time.perf_counter() - started, "base_url": "spawned by --serve" if args.serve else base_url,
                    "database": database_facts(db), "ollama": ollama_available()},
           "rows": rows, "scripts": script_rows, "v1": v1}
    if args.save_json:
        args.save_json.parent.mkdir(parents=True, exist_ok=True)
        args.save_json.write_text(json.dumps(run, indent=1), encoding="utf-8")
    baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
    if not args.only:
        write_report(args.report, render(run, baseline))
    summary = summarise(rows, script_rows, v1)
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
