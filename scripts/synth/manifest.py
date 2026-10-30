"""Manifest writer for synthetic ground-truth planted effects (DATA-4, DATA-9).

Writes human-readable data/SYNTHETIC_GROUND_TRUTH.md and machine-readable
data/synthetic_ground_truth.json sidecar.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PlantedEffectItem:
    effect_id: str
    name: str
    window: str
    target_table: str
    dimension: str
    true_mechanism: str
    expected_effect_size: str
    confounder: str
    recovery_engine: str
    parameters: dict[str, object]


class ManifestWriter:
    """Collects planted effects and serializes the evaluation answer key."""

    def __init__(self) -> None:
        self.effects: list[PlantedEffectItem] = []

    def record_effect(
        self,
        *,
        effect_id: str,
        name: str,
        window: str,
        target_table: str,
        dimension: str,
        true_mechanism: str,
        expected_effect_size: str,
        confounder: str,
        recovery_engine: str,
        parameters: dict[str, object] | None = None,
    ) -> None:
        self.effects.append(
            PlantedEffectItem(
                effect_id=effect_id,
                name=name,
                window=window,
                target_table=target_table,
                dimension=dimension,
                true_mechanism=true_mechanism,
                expected_effect_size=expected_effect_size,
                confounder=confounder,
                recovery_engine=recovery_engine,
                parameters=parameters or {},
            )
        )

    def write(self, data_dir: str | Path) -> tuple[Path, Path]:
        out_dir = Path(data_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        md_path = out_dir / "SYNTHETIC_GROUND_TRUTH.md"
        json_path = out_dir / "synthetic_ground_truth.json"

        # Machine-readable sidecar
        data_payload = {
            "version": "2.0.0",
            "seed": 42,
            "effects": [asdict(e) for e in self.effects],
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data_payload, f, indent=2)

        # Human-readable markdown answer key
        lines = [
            "# Synthetic Ground Truth Answer Key (V2 Evaluation)",
            "",
            "> **CONFIDENTIAL / EVALUATION ONLY** (DATA-4, DATA-9)",
            "> This document records the planted causal mechanisms, windows, effect sizes,",
            "> and confounders across the synthetic data layer (`brazil_ecommerce_v2.sqlite`).",
            "> Agents must never read this document during live reasoning.",
            "",
            "## Summary of Planted Effects",
            "",
            "| ID | Name | Window | Table | Dimension | Expected Effect Size | Recovery Engine | Confounder |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]

        for e in self.effects:
            lines.append(
                f"| **{e.effect_id}** | {e.name} | `{e.window}` | `{e.target_table}` | "
                f"{e.dimension} | {e.expected_effect_size} | `{e.recovery_engine}` | {e.confounder} |"
            )

        lines.extend(
            [
                "",
                "## Detailed Effect Specifications",
                "",
            ]
        )

        for e in self.effects:
            lines.extend(
                [
                    f"### {e.effect_id}: {e.name}",
                    f"- **Target Window:** `{e.window}`",
                    f"- **Target Table:** `{e.target_table}`",
                    f"- **Dimension Filter:** `{e.dimension}`",
                    f"- **True Mechanism:** {e.true_mechanism}",
                    f"- **Expected Effect Size:** {e.expected_effect_size}",
                    f"- **Recovery Engine:** `{e.recovery_engine}`",
                    f"- **Planted Confounder:** {e.confounder}",
                    f"- **Parameters:** `{json.dumps(e.parameters)}`",
                    "",
                ]
            )

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        return md_path, json_path
