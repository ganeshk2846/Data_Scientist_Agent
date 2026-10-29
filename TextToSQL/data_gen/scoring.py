"""Scoring-only access to synthetic ground truth (DATA-4/DATA-9).

Runtime query modules do not import this module. The manifest is stored outside
the generated warehouse directory; process-level isolation still requires the
evaluation runner to run under a separate OS identity.
"""
import hashlib
import json
from pathlib import Path
import tempfile


def load_ground_truth(snapshot_id: str, database_sha256: str, *, principal: str | None = None,
                      scoring_policy=None, truth_dir: str | Path | None = None) -> dict:
    if scoring_policy is None:
        raise PermissionError("ground truth is denied without a configured scoring authorization policy")
    scoring_policy.require(principal)
    if not snapshot_id or not database_sha256:
        raise ValueError("snapshot_id and database_sha256 are required")
    root = Path(truth_dir) if truth_dir is not None else Path(tempfile.gettempdir()) / "texttosql-scoring-truth"
    path = root / f"v5-{snapshot_id}-{database_sha256[:16]}.json"
    if not path.exists():
        # Read-only compatibility for existing v4 scoring artifacts.
        path = root / f"v4-{snapshot_id}-{database_sha256[:16]}.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("snapshot_id") != snapshot_id:
        raise ValueError("ground-truth snapshot mismatch")
    if document.get("database_sha256", database_sha256) != database_sha256:
        raise ValueError("ground-truth database hash mismatch")
    return document


def hash_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
