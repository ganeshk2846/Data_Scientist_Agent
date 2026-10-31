"""The evaluation answer key for the planted effects (DATA-4, DATA-9, V2-SYN-5).

Two outputs, written by the generator and read only by scoring code:

* ``data/SYNTHETIC_GROUND_TRUTH.md`` - human-readable, **committed**. It is
  rendered from the *planted parameters* only (table, period, dimension,
  planted effect size), so it is identical whichever source snapshot the
  generator ran on, and a test holds the committed file equal to it.
* ``data/synthetic_ground_truth.json`` - the machine-readable sidecar, built
  next to the database it describes. It adds the *realised* effect measured
  on the generated rows and the database's SHA-256, plus a V1
  ``GroundTruthManifest`` section for the existing scoring code. It is a
  build artefact, like the database, and is not committed.

Nothing is planted without an entry: every plant calls :meth:`ManifestWriter.effect`
or :meth:`ManifestWriter.confounder` for each change it makes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Role = Literal["effect", "confounder", "negative_control"]


@dataclass(frozen=True)
class PlantedFact:
    plant: str                    # "E1".."E5"
    fact_id: str                  # unique, e.g. "E1-spend"
    role: Role
    table: str
    column: str
    period_start: str             # inclusive, YYYY-MM-DD
    period_end: str               # inclusive, YYYY-MM-DD
    dimension: str                # what the effect is scoped to
    dimension_values: tuple[str, ...]
    planted_effect: str           # the exact change applied, in words
    expected_pct: float | None    # planted relative change, e.g. -0.40
    is_cause: bool
    note: str = ""
    realised_pct: float | None = None
    realised_rows: int | None = None    # rows added, for plants that insert rows


@dataclass
class ManifestWriter:
    seed: int
    generator_version: str
    facts: list[PlantedFact] = field(default_factory=list)

    def record(self, fact: PlantedFact) -> PlantedFact:
        if any(existing.fact_id == fact.fact_id for existing in self.facts):
            raise ValueError(f"duplicate planted fact {fact.fact_id!r}")
        self.facts.append(fact)
        return fact

    def by_plant(self, plant: str) -> list[PlantedFact]:
        return [fact for fact in self.facts if fact.plant == plant]

    # ------------------------------------------------------------------ #

    def to_json(self, *, database_sha256: str, snapshot_id: str) -> dict:
        return {
            "snapshot_id": snapshot_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "database_sha256": database_sha256,
            "facts": [asdict(fact) for fact in self.facts],
            "v1_manifest": self._v1_manifest(snapshot_id),
        }

    def _v1_manifest(self, snapshot_id: str) -> dict:
        """The subset expressible as a V1 ``GroundTruthManifest``."""
        anomalies, drivers, confounders = [], [], []
        effects = [fact for fact in self.facts if fact.role == "effect" and not fact.is_cause]
        causes = [fact for fact in self.facts if fact.role == "effect" and fact.is_cause]
        for outcome in effects:
            for value in outcome.dimension_values:
                anomaly_id = f"{outcome.fact_id}-{value}".replace(" ", "_")
                anomalies.append({
                    "anomaly_id": anomaly_id,
                    "metric": outcome.column,
                    "unit": {"dimension": outcome.dimension, "value": value},
                    "kind": "dip" if (outcome.expected_pct or 0) < 0 else "spike",
                    "start": outcome.period_start,
                    "end": outcome.period_end,
                    "magnitude_pct": round(100 * (outcome.expected_pct or 0), 4),
                })
                for cause in (c for c in causes if c.plant == outcome.plant):
                    drivers.append({
                        "anomaly_id": anomaly_id,
                        "cause_kind": _CAUSE_KIND.get(cause.plant, "segment"),
                        "cause": {"dimension": cause.dimension, "value": cause.dimension_values[0]},
                        "true_share": 1.0,
                    })
                for confounder in self.facts:
                    if confounder.plant == outcome.plant and confounder.role == "confounder":
                        confounders.append({
                            "anomaly_id": anomaly_id,
                            "moves_with": {
                                "dimension": confounder.dimension,
                                "value": confounder.dimension_values[0],
                            },
                            "is_cause": False,
                        })
        return {
            "snapshot_id": snapshot_id,
            "seed": self.seed,
            "generator_version": self.generator_version,
            "split": "build",
            "anomalies": anomalies,
            "drivers": drivers,
            "confounders": confounders,
        }

    def render_markdown(self) -> str:
        lines = [
            "# Synthetic ground truth - evaluation answer key",
            "",
            "**Generated by `scripts/synth/generate.py`. Do not edit by hand.**",
            "",
            "This file is the answer key for the planted effects in",
            "`data/brazil_ecommerce_v2.sqlite` (`DATA-4`, `V2-SYN-5`). Only",
            "scoring code reads it; the agent never does (`DATA-9`).",
            "",
            "Every effect is applied **only through synthetic tables**. No real",
            "Olist row is modified (`V2-SYN-1`), so where the spec describes an",
            "effect on a real metric (order count, AOV, review score, freight),",
            "the planted outcome is the synthetic table and column named below.",
            "",
            f"- Seed: `{self.seed}`",
            f"- Generator version: `{self.generator_version}`",
            "- Realised effect sizes measured on the generated rows, and the",
            "  database checksum, are in the build-time sidecar",
            "  `data/synthetic_ground_truth.json`.",
            "",
        ]
        for plant in sorted({fact.plant for fact in self.facts}):
            facts = self.by_plant(plant)
            lines += [f"## {plant} - {_TITLES.get(plant, plant)}", ""]
            lines += [
                "| Fact | Role | Cause? | Table.column | Period | Dimension | Values | Planted effect | Expected size |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
            for fact in facts:
                size = "-" if fact.expected_pct is None else f"{fact.expected_pct:+.1%}"
                lines.append(
                    f"| `{fact.fact_id}` | {fact.role} | {'yes' if fact.is_cause else 'no'} "
                    f"| `{fact.table}.{fact.column}` | {fact.period_start} to {fact.period_end} "
                    f"| `{fact.dimension}` | {', '.join(fact.dimension_values)} "
                    f"| {fact.planted_effect} | {size} |"
                )
            notes = [fact for fact in facts if fact.note]
            if notes:
                lines.append("")
                for fact in notes:
                    lines.append(f"- `{fact.fact_id}`: {fact.note}")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"


_TITLES = {
    "E1": "Marketing cut",
    "E2": "Stockouts",
    "E3": "Promotion: orders up, AOV down",
    "E4": "Delivery-delay spike",
    "E5": "Price change with a known elasticity",
}

_CAUSE_KIND = {"E1": "segment", "E2": "category", "E3": "price_change", "E4": "carrier", "E5": "price_change"}


def write_outputs(
    manifest: ManifestWriter,
    *,
    markdown_path: Path,
    json_path: Path,
    database_sha256: str,
    snapshot_id: str,
) -> None:
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(manifest.render_markdown(), encoding="utf-8")
    json_path.write_text(
        json.dumps(manifest.to_json(database_sha256=database_sha256, snapshot_id=snapshot_id), indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


__all__ = ["ManifestWriter", "PlantedFact", "write_outputs"]
