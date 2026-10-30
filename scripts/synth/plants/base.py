"""Base protocol for planted causal effects (Interfaces.md section 7.2)."""

from __future__ import annotations

import sqlite3
from typing import Protocol

import numpy as np

from scripts.synth.manifest import ManifestWriter


class PlantPlugin(Protocol):
    name: str

    def inject(
        self,
        conn: sqlite3.Connection,
        rng: np.random.Generator,
        manifest: ManifestWriter,
    ) -> None:
        """Inject causal effect into the synthetic tables and record in manifest."""
        ...
