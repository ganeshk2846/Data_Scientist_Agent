"""Development/held-out question split controls (DATA-6/DATA-8)."""
from __future__ import annotations

import json
from pathlib import Path
from .access import require_development_write


class QuestionSplitStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.heldout_path = self.path.with_name(f"{self.path.stem}.heldout{self.path.suffix}")

    def create(self, cases: list[dict]) -> None:
        require_development_write("question split mutation")
        ids = set()
        safe = []
        for case in cases:
            if not case.get("id") or case["id"] in ids:
                raise ValueError("question ids must be present and unique")
            if case.get("split") not in {"development", "held-out"}:
                raise ValueError("each question must be assigned to development or held-out")
            if not case.get("question"):
                raise ValueError("question text is required")
            ids.add(case["id"])
            safe.append({"id": case["id"], "split": case["split"], "question": case["question"],
                         "database_layer": case.get("database_layer", "synthetic_enterprise")})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        development = [case for case in safe if case["split"] == "development"]
        heldout = [case for case in safe if case["split"] == "held-out"]
        payloads = ((self.path, development), (self.heldout_path, heldout))
        legacy = None
        if self.path.exists() and not self.heldout_path.exists():
            try:
                current = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                current = None
            if current == safe:
                legacy = current
            elif current != development:
                raise FileExistsError("refusing to replace a locked question split")
        for target, cases_for_split in payloads:
            expected = json.dumps(cases_for_split, indent=2)
            if target.exists() and not (legacy is not None and target == self.path) and target.read_text(encoding="utf-8") != expected:
                raise FileExistsError("refusing to replace a locked question split")
        if legacy is not None:
            # Migrate the legacy mixed file only after both expected outputs
            # have been validated. The development file contains no held-out rows.
            self.path.write_text(json.dumps(development, indent=2), encoding="utf-8")
        for target, cases_for_split in payloads:
            if not target.exists():
                target.write_text(json.dumps(cases_for_split, indent=2), encoding="utf-8")

    def get(self, split: str, *, principal: str | None = None, scoring_policy=None) -> list[dict]:
        if split not in {"development", "held-out"}:
            raise ValueError("split must be development or held-out")
        if split == "held-out":
            if scoring_policy is None:
                raise PermissionError("held-out data is denied without a configured scoring authorization policy")
            scoring_policy.require(principal)
        source = self.heldout_path if split == "held-out" else self.path
        if not source.exists():
            raise FileNotFoundError(f"question split is not available: {split}")
        return json.loads(source.read_text(encoding="utf-8"))
