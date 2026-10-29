"""Load reproducible, unapproved BE-2 demonstration metric proposals."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .stores import MetricRegistry

DEFAULT_SEEDS = Path(__file__).resolve().parents[2] / "data" / "metric_registry_seeds.json"


def seed_registry(registry_path: str | Path, seeds_path: str | Path = DEFAULT_SEEDS) -> list[dict]:
    seeds = json.loads(Path(seeds_path).read_text(encoding="utf-8"))
    if not isinstance(seeds, list) or not seeds:
        raise ValueError("metric seed file must contain a non-empty list")
    if any(not isinstance(seed, dict) or not seed.get("seed_id") for seed in seeds):
        raise ValueError("every seed metric must have a stable seed_id")
    registry = MetricRegistry(registry_path)
    return [registry.propose(seed) for seed in seeds]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", default="data/metric_registry.json")
    parser.add_argument("--seeds", default=str(DEFAULT_SEEDS))
    args = parser.parse_args()
    proposals = seed_registry(args.registry, args.seeds)
    print(json.dumps({"seeded": len(proposals), "status": "proposed",
                      "registry": str(Path(args.registry)),
                      "metric_ids": [item["id"] for item in proposals]}, indent=2))


if __name__ == "__main__":
    main()
