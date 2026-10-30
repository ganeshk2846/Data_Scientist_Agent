"""Rebuild ``data/brazil_ecommerce_v2.sqlite`` with one command.

    python scripts/build_v2.py                       # from ./brazil_ecommerce.sqlite
    python scripts/build_v2.py --source path/to/olist.sqlite
    python scripts/build_v2.py --fixture             # no snapshot: seeded stand-in

1. ``scripts/synth/generate.py`` - copy the real tables, add the synthetic
   tables and planted effects, write the answer key, create indexes.
2. ``scripts/build_analytical_tables.py`` - precompute the analytical tables.

The real snapshot is only ever opened read-only. ``--fixture`` builds the
Olist-shaped test fixture first and uses it as the source, so the pipeline
can be exercised without the snapshot; its figures describe nothing real.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.build_analytical_tables import build
from scripts.synth.fixture import build_fixture
from scripts.synth.generate import (
    DEFAULT_MARKDOWN,
    DEFAULT_SEED,
    DEFAULT_SOURCE,
    DEFAULT_TARGET,
    generate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--fixture", action="store_true", help="build from the seeded Olist-shaped fixture")
    parser.add_argument("--computed-at", default=None, help="timestamp for analytical rows (default: now)")
    args = parser.parse_args(argv)

    source = args.source
    markdown = DEFAULT_MARKDOWN
    if args.fixture:
        source = build_fixture(args.target.with_name("olist_fixture.sqlite"))
        print(f"fixture source: {source}")
    elif not source.is_file():
        parser.error(f"{source} not found: pass --source, or --fixture to build without the snapshot")

    result = generate(source, args.target, seed=args.seed, markdown_path=markdown)
    counts = build(result.target, computed_at=args.computed_at)

    rows = {**result.row_counts, **counts}
    width = max(len(name) for name in rows)
    for name, count in rows.items():
        print(f"{name:<{width}}  {count:>12,}")
    print(f"\n{result.target}\nsha256 {result.database_sha256} (before analytical tables)")
    print(f"answer key {markdown}")
    print(f"\nexport DS_AGENT_DB={result.target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
