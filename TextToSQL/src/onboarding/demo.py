"""Offline end-to-end BE-2 onboarding and catalog-grounded query demo."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from data_gen.generator import generate
from src.onboarding.pipeline import build_catalog
from src.knowledge.stores import TraceStore
from src.spike import answer


class _DemoLLM:
    def chat(self, system: str, user: str):
        if "TABLE ord_hdr" not in user:
            return SimpleNamespace(text=json.dumps({"sql": None, "reasoning": "ord_hdr is absent from retrieved schema"}), latency_ms=0)
        return SimpleNamespace(text=json.dumps({"sql": "SELECT COUNT(*) AS order_count FROM ord_hdr", "reasoning": "count catalogued order rows"}),
                               latency_ms=0, prompt_tokens=0, completion_tokens=0, cost_usd=0.0)


def run_demo() -> dict:
    with tempfile.TemporaryDirectory(prefix="texttosql-be2-demo-") as temporary:
        root = Path(temporary)
        warehouse = root / "warehouse.sqlite"
        truth_dir = root / "scoring"
        output = root / "catalog"
        manifest = generate(warehouse, table_count=50, seed=31, snapshot="development", truth_dir=truth_dir)
        report = build_catalog(warehouse, output)
        result = answer(_DemoLLM(), "demo", "count ord_hdr records", catalog_dir=output,
                        trace_path=root / "traces.json", warehouse_path=warehouse)
        if result.get("status") != "ok" or not report["self_test"]["passed"]:
            raise RuntimeError(f"BE-2 demo failed: {result.get('status')}")
        trace_count = len(TraceStore(root / "traces.json").get(result["run_id"]))
        if trace_count < 2:
            raise RuntimeError(f"BE-2 demo expected at least two trace events for run {result['run_id']}; found {trace_count}")
        return {"catalog_version": report["catalog_version"], "table_count": report["table_count"],
                "catalog_artifacts": sorted(path.name for path in output.glob("*.json")),
                "retrieved_tables": result["retrieved_tables"], "query": result["sql"],
                "result": result["rows"], "context_tokens_estimated": result["schema_tokens_estimated"],
                "retrieval_mode": result["retrieval_mode"], "trace_events": trace_count,
                "snapshot_id": manifest["snapshot_id"], "temporary_data_removed": True}


def main():
    print(json.dumps(run_demo(), indent=2))


if __name__ == "__main__":
    main()
