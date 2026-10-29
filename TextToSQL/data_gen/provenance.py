"""Public dataset provenance registry (metadata only; no dataset downloader)."""
import json
import hashlib
import os
import tempfile
from pathlib import Path
from urllib.parse import urlparse
from .access import require_development_write

FIELDS = ("name", "url", "version", "licence", "permitted_use", "split", "layer")
OPTIONAL_FIELDS = ("citation", "doi", "intake_status", "source_sha256",
                   "artifact_sha256", "transformation", "privacy_approval_ref",
                   "privacy_approval_reviewer", "privacy_approval_reviewed_at")


def directory_sha256(directory: str | Path) -> str:
    """Hash a directory snapshot by sorted relative path and file digest."""
    root = Path(directory).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"dataset snapshot contains a path outside its root: {path.relative_to(root)}")
        file_digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                file_digest.update(chunk)
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def register_dataset(record: dict, path: str | Path = "data/provenance.json") -> dict:
    require_development_write("dataset provenance mutation")
    if not isinstance(record, dict):
        raise ValueError("Dataset provenance must be a JSON object")
    missing = [field for field in FIELDS if not record.get(field)]
    if missing:
        raise ValueError(f"Dataset provenance requires: {', '.join(missing)}")
    for field in FIELDS:
        if not isinstance(record[field], str) or not record[field].strip():
            raise ValueError(f"Dataset provenance field {field} must be non-empty text")
    parsed_url = urlparse(record["url"])
    if parsed_url.scheme not in {"http", "https", "local"} or (parsed_url.scheme in {"http", "https"} and not parsed_url.netloc):
        raise ValueError("Dataset provenance URL must be an HTTP(S) URL or explicit local:// fixture")
    if not record["licence"].strip() or not record["permitted_use"].strip():
        raise ValueError("Dataset provenance must state its licence and permitted use")
    if record["split"] not in ("development", "held-out"):
        raise ValueError("split must be development or held-out")
    if record["layer"] not in ("benchmark", "public_transactional", "synthetic_enterprise"):
        raise ValueError("layer must identify benchmark, public_transactional or synthetic_enterprise")
    if record.get("intake_status", "ingested") not in ("candidate_not_ingested", "ingested", "excluded"):
        raise ValueError("intake_status must be candidate_not_ingested, ingested or excluded")
    status = record.get("intake_status", "ingested")
    if status == "ingested" and not (record.get("source_sha256") or record.get("artifact_sha256")):
        raise ValueError("ingested datasets require a source or artifact SHA-256 provenance digest")
    if record.get("source_sha256") and (len(record["source_sha256"]) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in record["source_sha256"])):
        raise ValueError("source_sha256 must be a 64-character hexadecimal SHA-256 digest")
    if record.get("artifact_sha256") and (len(record["artifact_sha256"]) != 64 or any(ch not in "0123456789abcdefABCDEF" for ch in record["artifact_sha256"])):
        raise ValueError("artifact_sha256 must be a 64-character hexadecimal SHA-256 digest")
    target = Path(path)
    rows = json.loads(target.read_text(encoding="utf-8")) if target.exists() else []
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Dataset provenance file must contain a JSON list of records")
    rows = [row for row in rows if not (row["name"] == record["name"] and row["version"] == record["version"])]
    rows.append({field: record[field] for field in FIELDS}
                | {field: record[field] for field in OPTIONAL_FIELDS if record.get(field) is not None})
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(rows, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        Path(temporary).unlink(missing_ok=True)
        raise
    return rows[-1]
