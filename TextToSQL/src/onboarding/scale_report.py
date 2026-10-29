"""Reproducible local BE-2 scale report (generation plus onboarding).

This is a single-run local observation, not an SLA or cloud-cost benchmark.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from data_gen.generator import generate
from src.knowledge.dense_index import ENCODER_VERSION
from src.onboarding.pipeline import build_catalog


def collect_scale_report(sizes=(50, 200, 500), *, seed: int = 7) -> dict:
    runs = []
    with tempfile.TemporaryDirectory(prefix="texttosql-be2-scale-") as temporary:
        root = Path(temporary)
        for size in sizes:
            case = root / f"{size}"
            case.mkdir(parents=True)
            warehouse = case / "warehouse.sqlite"
            truth = case / "scoring"
            output = case / "catalog"

            started = time.perf_counter()
            manifest = generate(warehouse, table_count=size, seed=seed,
                                snapshot="development", truth_dir=truth)
            generation_seconds = time.perf_counter() - started

            started = time.perf_counter()
            report = build_catalog(warehouse, output)
            onboarding_seconds = time.perf_counter() - started

            index = json.loads((output / "index_build.json").read_text(encoding="utf-8"))
            dense = index.get("dense", {})
            runs.append({
                "tables": size,
                "generation_seconds": round(generation_seconds, 3),
                "onboarding_seconds": round(onboarding_seconds, 3),
                "dense_vectors": len(dense.get("vectors", {})),
                "dense_backend": dense.get("backend"),
                "encoder_version": dense.get("encoder_version"),
                "self_test_passed": bool(report["self_test"]["passed"]),
                "status": report["status"],
                "snapshot_id": manifest["snapshot_id"],
            })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "encoder_version": ENCODER_VERSION,
        },
        "seed": seed,
        "runs": runs,
        "cost": {
            "measured": False,
            "estimated_cost_usd": None,
            "note": "Local elapsed time only; no cloud spend or provider pricing was measured.",
        },
        "note": "Single local run per size. Not an SLA, benchmark, or production cost measurement.",
    }


def render_markdown(result: dict) -> str:
    env = result["environment"]
    lines = [
        "# BE-2 local scale report",
        "",
        f"Generated: {result['generated_at']}",
        f"Environment: Python {env['python']}; {env['platform']}",
        f"Seed: {result['seed']}; encoder: {env['encoder_version']}",
        "",
        "| Tables | Generate (s) | Onboard (s) | Dense vectors | Self-test | Status |",
        "|---:|---:|---:|---:|:---:|:---|",
    ]
    for run in result["runs"]:
        lines.append(
            f"| {run['tables']} | {run['generation_seconds']:.3f} | "
            f"{run['onboarding_seconds']:.3f} | {run['dense_vectors']} | "
            f"{'passed' if run['self_test_passed'] else 'failed'} | {run['status']} |"
        )
    lines += [
        "",
        "Reproduce with:",
        "",
        "```text",
        "python -m src.onboarding.scale_report --sizes 50 200 500",
        "```",
        "",
        "## Limitations",
        "",
        f"- {result['note']}",
        f"- {result['cost']['note']}",
        "- Temporary warehouses and truth directories are removed after each run.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[50, 200, 500])
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output", default="contracts/BE2_SCALE_REPORT.md")
    args = parser.parse_args()
    result = collect_scale_report(tuple(args.sizes), seed=args.seed)
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.casefold() == ".json":
        destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    else:
        destination.write_text(render_markdown(result), encoding="utf-8")
    print(f"wrote {destination}")


if __name__ == "__main__":
    main()
