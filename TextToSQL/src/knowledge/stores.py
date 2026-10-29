"""Local, version-aware stores for BE-2 governance and query-time artifacts."""
from __future__ import annotations

import hashlib
import json
import re
import contextlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from src.onboarding.privacy import redact_payload
from data_gen.access import require_development_write


def _load(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _save(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


@contextlib.contextmanager
def _locked_data(path: Path, default):
    """Serialize read/modify/write operations across local processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("a+b") as lock_file:
        if lock_file.seek(0, 2) == 0:
            lock_file.write(b"0")
            lock_file.flush()
        lock_file.seek(0)
        if __import__("os").name == "nt":
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _load(path, default)
            yield data
            _save(path, data)
        finally:
            lock_file.seek(0)
            if __import__("os").name == "nt":
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


class MetricRegistry:
    REQUIRED = {"name", "synonyms", "formula", "required_filters", "grain", "date_column", "allowed_dimensions", "base_table", "join_path", "caveats", "reconciliation_values"}

    def __init__(self, path: str | Path, *, reviewer_authorizer=None):
        self.path = Path(path)
        # Identity authentication belongs to the host API. The local registry
        # denies every review unless the host supplies an authorization policy.
        self.reviewer_authorizer = reviewer_authorizer

    def propose(self, metric: dict):
        require_development_write("metric-registry mutation")
        if not isinstance(metric, dict):
            raise ValueError("Metric definition must be an object")
        missing = self.REQUIRED - metric.keys()
        if missing:
            raise ValueError(f"Metric missing fields: {sorted(missing)}")
        for field in ("name", "formula", "date_column", "base_table"):
            if not isinstance(metric[field], str) or not metric[field].strip():
                raise ValueError(f"Metric field {field} must be non-empty text")
        for field in ("synonyms", "required_filters", "allowed_dimensions", "caveats"):
            if not isinstance(metric[field], list) or any(not isinstance(value, str) or not value.strip()
                                                          for value in metric[field]):
                raise ValueError(f"Metric field {field} must be a list of non-empty strings")
        if not (isinstance(metric["grain"], str) and metric["grain"].strip()
                or isinstance(metric["grain"], list) and metric["grain"]
                and all(isinstance(value, str) and value.strip() for value in metric["grain"])):
            raise ValueError("Metric field grain must be non-empty text or a list of non-empty strings")
        if not isinstance(metric["join_path"], list) or any(not isinstance(edge, dict) for edge in metric["join_path"]):
            raise ValueError("Metric field join_path must be a list of join-edge objects")
        if not isinstance(metric["reconciliation_values"], dict):
            raise ValueError("Metric field reconciliation_values must be an object")
        with _locked_data(self.path, []) as rows:
            seed_id = metric.get("seed_id")
            if seed_id:
                existing_seed = next((row for row in rows if row.get("seed_id") == seed_id), None)
                if existing_seed is not None:
                    return existing_seed
            metric_id = hashlib.sha1(metric["name"].casefold().encode()).hexdigest()[:12]
            revision = max((r.get("version", 0) for r in rows if r.get("id") == metric_id), default=0) + 1
            item = {**redact_payload(metric), "status": "proposed", "id": metric_id, "version": revision,
                    "decision_history": [{"status": "proposed", "reviewer": None, "recorded_at": datetime.now(timezone.utc).isoformat()}]}
            rows.append(item)
        return item

    def decide(self, metric_id: str, *, approve: bool, reviewer: str | None = None, note: str | None = None, version: int | None = None):
        require_development_write("metric-registry mutation")
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise ValueError("A named human reviewer is required")
        if note is not None and (not isinstance(note, str) or len(note) > 2000):
            raise ValueError("Metric review note must be text no longer than 2,000 characters")
        if type(approve) is not bool:
            raise ValueError("Metric decision must be an explicit boolean approval or rejection")
        if not approve and (not note or not note.strip()):
            raise ValueError("A reason is required to reject a metric definition")
        reviewer_id = reviewer.strip()
        if self.reviewer_authorizer is None or self.reviewer_authorizer(reviewer_id) is not True:
            raise PermissionError("Reviewer is not authorized to decide metric definitions")
        with _locked_data(self.path, []) as rows:
            candidates = [row for row in rows if row["id"] == metric_id and (version is None or row.get("version") == version)]
            if not candidates:
                raise KeyError(metric_id)
            row = max(candidates, key=lambda item: item.get("version", 0))
            if row["status"] != "proposed":
                raise ValueError("Only proposed metric revisions can be reviewed")
            row["status"] = "approved" if approve else "rejected"
            row.setdefault("decision_history", []).append({"status": row["status"], "reviewer": reviewer_id,
                "authorization": "authorized_by_host_policy",
                "note": redact_payload(note) if note is not None else None,
                "recorded_at": datetime.now(timezone.utc).isoformat()})

    def approved(self):
        rows = _load(self.path, [])
        latest = {}
        for row in rows:
            if row["id"] not in latest or row.get("version", 0) > latest[row["id"]].get("version", 0):
                latest[row["id"]] = row
        return [row for row in latest.values() if row["status"] == "approved"]

    def resolve(self, term: str):
        wanted = term.strip().casefold()
        matches = [row for row in self.approved()
                   if wanted == row["name"].casefold() or wanted in {str(value).casefold() for value in row.get("synonyms", [])}]
        return matches[0] if len(matches) == 1 else None

    def get(self, metric_id: str):
        rows = [row for row in _load(self.path, []) if row["id"] == metric_id]
        if not rows:
            raise KeyError(metric_id)
        return max(rows, key=lambda item: item.get("version", 0))


class GoldenStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def promote(self, record: dict, *, result_checks_passed: bool, human_approved: bool,
                reviewer: str | None = None, dataset_split: str = "development",
                heldout_questions: list[str] | None = None):
        require_development_write("Golden Store mutation")
        if dataset_split != "development":
            raise ValueError("Only development-set material can be promoted")
        if not result_checks_passed or not human_approved:
            raise ValueError("Golden promotion requires passing result checks and human approval")
        if not reviewer or not reviewer.strip():
            raise ValueError("A named human reviewer is required")
        if not heldout_questions:
            raise ValueError("A non-empty held-out question set is required for Golden promotion")
        if not self.leakage_check(heldout_questions, candidate=record)["passed"]:
            raise ValueError("Golden promotion is blocked by held-out question leakage")
        with _locked_data(self.path, []) as rows:
            rows.append({**redact_payload(record), "status": "approved", "dataset_split": dataset_split,
                         "verified_by": reviewer.strip(), "verified_at": datetime.now(timezone.utc).isoformat()})

    def assert_final_run_safe(self, heldout_questions: list[str]) -> dict:
        result = self.leakage_check(heldout_questions)
        if not result["passed"]:
            raise ValueError("Final evaluation blocked by Golden Store leakage")
        return result

    def propose(self, question: str, sql: str, source_run_id: str, checks: list[dict], *,
                tables: list[str] | None = None, metric_ids: list[str] | None = None,
                catalog_version: str | None = None) -> str:
        require_development_write("Golden Store mutation")
        if not question.strip() or not sql.strip() or not source_run_id:
            raise ValueError("Golden candidate requires question, SQL and source_run_id")
        candidate_id = hashlib.sha256(f"{source_run_id}|{question}|{sql}".encode()).hexdigest()[:16]
        with _locked_data(self.path, []) as rows:
            if any(row.get("entry_id") == candidate_id for row in rows):
                return candidate_id
            rows.append({"entry_id": candidate_id, "question": question, "sql": sql, "source_run_id": source_run_id,
                         "checks": redact_payload(checks), "tables": tables or [], "metric_ids": metric_ids or [],
                         "catalog_version": catalog_version, "status": "proposed", "dataset_split": "development"})
        return candidate_id

    def decide(self, candidate_id: str, *, approve: bool, reviewer: str,
               result_checks_passed: bool, heldout_questions: list[str] | None = None,
               rejection_reason: str | None = None):
        require_development_write("Golden Store mutation")
        if not reviewer.strip():
            raise ValueError("A named human reviewer is required")
        with _locked_data(self.path, []) as rows:
            candidate = next((row for row in rows if row.get("entry_id") == candidate_id), None)
            if candidate is None:
                raise KeyError(candidate_id)
            if candidate.get("status") != "proposed":
                raise ValueError("Only proposed Golden candidates can be reviewed")
            if candidate.get("dataset_split") != "development":
                raise ValueError("Only development-set material can be approved")
            if not approve and not (rejection_reason and rejection_reason.strip()):
                raise ValueError("A rejection reason is required")
            if approve:
                if not result_checks_passed or not candidate.get("checks") or not all(check.get("passed") for check in candidate["checks"]):
                    raise ValueError("Golden promotion requires passing result checks")
                if not heldout_questions:
                    raise ValueError("A non-empty held-out question set is required for Golden approval")
                if not self.leakage_check(heldout_questions, candidate=candidate)["passed"]:
                    raise ValueError("Golden promotion is blocked by held-out question leakage")
                candidate.update({"status": "approved", "verified_by": reviewer.strip(),
                                  "verified_at": datetime.now(timezone.utc).isoformat()})
            else:
                candidate.update({"status": "rejected", "reviewed_by": reviewer.strip(),
                                  "reviewed_at": datetime.now(timezone.utc).isoformat(),
                                  "rejection_reason": rejection_reason.strip()})

    def nearest(self, question: str, k: int = 3):
        words = lambda text: set(re.findall(r"[a-z0-9]+", text.casefold()))
        query = words(question)
        ranked = []
        for row in _load(self.path, []):
            if row.get("status") != "approved" or row.get("dataset_split") != "development":
                continue
            terms = words(row.get("question", ""))
            score = len(query & terms) / max(1, len(query | terms))
            if score:
                ranked.append((score, row))
        return [row for _, row in sorted(ranked, key=lambda item: (-item[0], item[1].get("entry_id", "")))[:k]]

    def leakage_check(self, heldout_questions: list[str], *, threshold: float = 0.8, candidate: dict | None = None):
        normalize = lambda text: set(re.findall(r"[a-z0-9]+", text.casefold()))
        held = [(q, normalize(q)) for q in heldout_questions]
        leaks = []
        entries = _load(self.path, [])
        if candidate is not None:
            entries = [*entries, candidate]
        for item in entries:
            question = item.get("question", "")
            words = normalize(question)
            for held_text, held_words in held:
                similarity = len(words & held_words) / max(1, min(len(words), len(held_words)))
                if similarity >= threshold:
                    leaks.append({"gold_question": question, "heldout_question": held_text, "similarity": round(similarity, 3)})
        return {"passed": not leaks, "leaks": leaks}


class TraceStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, trace: dict):
        require_development_write("Trace Store write")
        safe_trace = redact_payload(trace)
        run_id = trace.get("run_id") if isinstance(trace, dict) else None
        # UUID run identifiers are generated correlation metadata, not user
        # content. Preserve canonical UUIDs so a redacted phone/email substring
        # cannot accidentally make an otherwise safe trace unqueryable.
        if isinstance(run_id, str):
            try:
                if str(uuid.UUID(run_id)) == run_id:
                    safe_trace["run_id"] = run_id
            except ValueError:
                pass
        with _locked_data(self.path, []) as rows:
            rows.append(safe_trace)

    def write(self, event: dict):
        self.append(event)

    def get(self, run_id: str):
        return [row for row in _load(self.path, []) if row.get("run_id") == run_id]


class CatalogCache:
    def __init__(self, path: str | Path, catalog_version: str):
        self.path = Path(path)
        self.version = catalog_version

    def get(self, key: str):
        store = _load(self.path, {})
        item = store.get(key)
        return item["value"] if item and item["catalog_version"] == self.version else None

    def put(self, key: str, value):
        require_development_write("Catalog cache write")
        with _locked_data(self.path, {}) as store:
            store[key] = {"catalog_version": self.version, "value": redact_payload(value)}


class ActionLibrary:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def put(self, action_id: str, content):
        require_development_write("Action Library mutation")
        with _locked_data(self.path, {}) as rows:
            rows[action_id] = redact_payload(content)

    def get(self, action_id: str):
        return _load(self.path, {}).get(action_id)

    def match(self, driver_types: list[str]):
        requested = {value.casefold() for value in driver_types}
        return [item for item in _load(self.path, {}).values()
                if requested.intersection(str(value).casefold() for value in item.get("driver_types", []))]


class FeedbackStore:
    """Development-only feedback records with an explicit evaluation gate."""
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def append(self, record: dict):
        require_development_write("Feedback Store write")
        if record.get("dataset_split") != "development":
            raise ValueError("Feedback learning is restricted to the development split")
        if not record.get("run_id") or not record.get("correction"):
            raise ValueError("Feedback requires run_id and correction")
        with _locked_data(self.path, []) as rows:
            rows.append(redact_payload({**record, "recorded_at": datetime.now(timezone.utc).isoformat(), "status": "pending_dev_evaluation"}))

    def list_pending(self):
        return [row for row in _load(self.path, []) if row.get("status") == "pending_dev_evaluation"]

    def record_evaluation(self, run_ids: list[str], *, split: str, passed: bool, reviewer: str):
        require_development_write("Feedback Store evaluation write")
        if split != "development":
            raise ValueError("Feedback updates must be evaluated on development data first")
        if not reviewer.strip():
            raise ValueError("A named reviewer is required")
        with _locked_data(self.path, []) as rows:
            for row in rows:
                if row.get("run_id") in run_ids:
                    row["status"] = "eligible_for_scheduled_update" if passed else "rejected_by_dev_evaluation"
                    row["evaluation"] = {"split": split, "passed": passed, "reviewer": reviewer,
                                         "recorded_at": datetime.now(timezone.utc).isoformat()}
