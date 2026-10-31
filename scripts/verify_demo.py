"""Replay the V2 demo (scripts/demo_v2.yaml) live and fail if any step does not pass.

Every step goes over HTTP to ``POST /api/v2/ask``, exactly as the UI sends it, and the
finished envelope is checked: the expected status and primary intent; for an answer, a
conclusion, at least one ledger claim, and a terminal SSE stream. It also checks that the
hero chips in ``SuggestionChips.tsx`` are exactly the demo's ``hero_chips``, in order, and that
each one opens a demo scene - so a chip can never drift onto a question that was not just replayed.

    python scripts/verify_demo.py --serve                      # the default V2 build
    python scripts/verify_demo.py --serve --db path/to/v2.sqlite
    python scripts/verify_demo.py --serve --probe "Why did revenue spike in May 2018?"
"""

from __future__ import annotations

import argparse
import json
import re
import secrets
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_v2 import DEFAULT_DB, ROOT, Client, intents_of, serve

DEMO = ROOT / "scripts" / "demo_v2.yaml"
CHIPS = ROOT / "frontend" / "web" / "src" / "components" / "ask" / "SuggestionChips.tsx"


def hero_chips() -> list[str]:
    """The SUGGESTIONS array, read from the component source (no build needed)."""
    source = CHIPS.read_text(encoding="utf-8")
    block = source.split("export const SUGGESTIONS", 1)[1].split("];", 1)[0]
    return [json.loads(f'"{text}"') for text in re.findall(r"^\s*'((?:[^'\\]|\\.)*)',", block, re.MULTILINE)]


def check_step(step: dict, result: dict) -> list[str]:
    if "error" in result:
        return [result["error"]]
    envelope = result["envelope"]
    problems = []
    if envelope["status"] != step["expect"]:
        problems.append(f"status {envelope['status']} != {step['expect']}")
    intents = intents_of(envelope)
    if step.get("intent") and envelope["status"] == "answered" and intents[:1] != [step["intent"]]:
        problems.append(f"intent {intents} != {step['intent']}")
    if step["expect"] == "answered":
        if not (envelope.get("conclusion") or "").strip():
            problems.append("no conclusion")
        if not envelope.get("claims"):
            problems.append("no ledger claim")
    if not result.get("stream", {}).get("ok"):
        problems.append("SSE stream did not end on answer/error")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url")
    parser.add_argument("--token")
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--probe", action="append", default=[], help="also ask this question (reported, not gated)")
    parser.add_argument("--save-json", type=Path)
    args = parser.parse_args(argv)

    demo = yaml.safe_load(DEMO.read_text(encoding="utf-8"))
    scenes, chips = demo["scenes"], demo["hero_chips"]
    failures: list[str] = []
    if hero_chips() != chips:
        failures.append(f"SUGGESTIONS {hero_chips()} != hero_chips {chips}")
    openers = {scene["steps"][0]["q"] for scene in scenes}
    failures += [f"hero chip {chip!r} is not the first step of a demo scene" for chip in chips if chip not in openers]

    process, token, base = None, args.token, args.base_url
    if args.serve:
        token = token or secrets.token_hex(24)
        process, base = serve(args.db.resolve(), token)
    if not base:
        raise SystemExit("pass --base-url or --serve")
    report = []
    try:
        client = Client(base, token, timeout=120.0)
        client.ask("What data do you have?", session_id="demo-warmup")
        tag = secrets.token_hex(3)
        for scene in scenes:
            previous = None
            for number, step in enumerate(scene["steps"], 1):
                extra = {}
                if step.get("reply") == "default" and previous and "envelope" in previous:
                    clarification = previous["envelope"].get("clarification") or {}
                    extra = {"clarification_of": previous["run_id"],
                             "option_id": (clarification.get("default_assumption") or {}).get("option_id")}
                result = client.ask(step["q"], session_id=f"demo-{tag}-{scene['id']}", **extra)
                problems = check_step(step, result)
                envelope = result.get("envelope") or {}
                row = {"scene": scene["id"], "step": number, "q": step["q"], "status": envelope.get("status", "http_error"),
                       "intents": intents_of(envelope), "latency_ms": result.get("latency_ms"), "problems": problems,
                       "charts": len(envelope.get("visualizations", ())), "claims": len(envelope.get("claims", ())),
                       "options": len(envelope.get("next_actions", ())), "conclusion": (envelope.get("conclusion") or "")[:600]}
                report.append(row)
                print(f"{'PASS' if not problems else 'FAIL'}  {scene['id']:12} {number}  {row['status']:22} {row['latency_ms']:>6} ms  "
                      f"{step['q']}" + (f"  -- {'; '.join(problems)}" if problems else ""), flush=True)
                if problems:
                    failures.append(f"{scene['id']} step {number} ({step['q']}): {'; '.join(problems)}")
                previous = result
        for question in args.probe:
            result = client.ask(question, session_id=f"demo-{tag}-probe")
            envelope = result.get("envelope") or {}
            print(f"PROBE {envelope.get('status', result.get('error'))}  {result.get('latency_ms')} ms  {question}\n"
                  f"      {(envelope.get('conclusion') or '')[:300]}")
    finally:
        if process is not None:
            process.terminate()
            process.wait(timeout=20)
    if args.save_json:
        args.save_json.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{len(report) - sum(bool(row['problems']) for row in report)}/{len(report)} demo steps passed")
    for failure in failures:
        print("FAIL:", failure)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
