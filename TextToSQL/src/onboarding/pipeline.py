"""SQLite warehouse onboarding: catalog, profiles, governance, indexes and report."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .inspector import connect_read_only, inspect_warehouse
from .profiler import profile_database
from .privacy import make_redactor, redact_payload, sensitive_value, sensitive_variants
from src.knowledge.dense_index import build_dense_payload

STAGES = ["connect", "introspect", "profile", "mask", "trust_features", "join_discovery", "descriptions", "index_build", "dense_index", "knowledge_graph", "self_test", "report"]
SENSITIVE = re.compile(r"(^|_)(email|e_mail|phone|mobile|ssn|social_security|password|passwd|token|secret|address|birth|dob|credit_card|card_number|full_name|first_name|last_name|customer_name|username|ip_address|passport|tax_id|bank_account)(_|$)", re.I)


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=str), encoding="utf-8")
    temp.replace(path)


def _read(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _value_overlap(connection, left_table, left_col, right_table, right_col, cap=500):
    try:
        lt, lc, rt, rc = map(_quote, (left_table, left_col, right_table, right_col))
        left = {r[0] for r in connection.execute(f"SELECT DISTINCT {lc} FROM {lt} WHERE {lc} IS NOT NULL LIMIT {cap}")}
        right = {r[0] for r in connection.execute(f"SELECT DISTINCT {rc} FROM {rt} WHERE {rc} IS NOT NULL LIMIT {cap}")}
        return len(left & right) / max(1, min(len(left), len(right)))
    except Exception:
        return 0.0


def build_catalog(db_path: str | Path, output_dir: str | Path = "artifacts/catalog", *, sensitive_columns: list[str] | None = None, descriptions: dict[str, str] | None = None, resume: bool = True, dense_encoder=None) -> dict:
    """Build versioned knowledge artifacts from a read-only SQLite connection.

    Suggested sensitive column names are masked automatically. Pass fully qualified
    ``table.column`` values to add manual masking decisions. Suggestions keep the
    build in ``needs_review`` until explicitly resolved through review.json.
    """
    db_path, out = Path(db_path), Path(output_dir)
    if not db_path.is_file():
        raise FileNotFoundError(f"Database not found: {db_path}")
    out.mkdir(parents=True, exist_ok=True)
    encoder_version = getattr(dense_encoder, "encoder_version", "signed-word-char-ngram-v1")
    options_hash = hashlib.sha256(json.dumps({"pipeline_version": 2, "sensitive_columns": sorted(sensitive_columns or []), "descriptions": descriptions or {}, "dense_encoder_version": encoder_version}, sort_keys=True).encode()).hexdigest()
    warehouse_hash = _hash_file(db_path)
    source_hash = warehouse_hash + ":" + options_hash
    state_path = out / "job.json"
    old_catalog = _read(out / "catalog.json", {})
    previous_dense_index = _read(out / "index_build.json", {}).get("dense", {})
    review = _read(out / "review.json", {})
    description_decisions = review.get("description_decisions", {})
    previous = _read(state_path, {})
    same_job_input = bool(resume and previous.get("source_hash") == source_hash)
    state = previous if same_job_input else {"source_hash": source_hash, "stages": {}, "status": "running", "started_at": datetime.now(timezone.utc).isoformat()}
    state["status"] = "running"
    state["options_hash"] = options_hash
    sensitive_audit = review.get("sensitive_decisions", {})
    dismissed_sensitive = {name: item.get("reviewed_at") for name, item in sensitive_audit.items() if item.get("status") == "rejected"}
    for name in review.get("rejected_sensitive_columns", []):
        dismissed_sensitive.setdefault(name, None)
    processed_dismissals = state.get("dismissed_sensitive_reprofiled", {})
    reprofile_due = {name for name, timestamp in dismissed_sensitive.items() if processed_dismissals.get(name) != timestamp}
    reprofile_tables = {name.split(".", 1)[0] for name in reprofile_due if "." in name}
    manifest = {"source": db_path.name, "source_hash": source_hash, "started_at": state["started_at"], "stages": state["stages"]}
    _write(state_path, state)

    def stage(name, fn, force=False, persist=None):
        existing = state["stages"].get(name, {})
        artifact = out / f"{name}.json"
        if resume and not force and existing.get("status") == "complete" and artifact.exists():
            return _read(artifact, {})
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        state["stages"][name] = {"status": "running", "started_at": started_at}
        _write(state_path, state)
        try:
            value = fn()
        except Exception as error:
            state["stages"][name] = {
                "status": "failed", "started_at": started_at,
                "failed_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(time.perf_counter() - started, 3),
                "error": f"{type(error).__name__}: "
                f"{redact_payload(str(error))}"[:500],
            }
            state["status"] = "failed"
            _write(state_path, state)
            raise
        _write(artifact, persist(value) if persist else value)
        state["stages"][name] = {"status": "complete", "count": len(value) if hasattr(value, "__len__") else 1, "duration_seconds": round(time.perf_counter() - started, 3)}
        _write(state_path, state)
        return value

    connection_info = stage("connect", lambda: _connect_info(db_path))
    raw = stage("introspect", lambda: _introspect(db_path))
    if old_catalog.get("warehouse_hash") == warehouse_hash:
        signatures = old_catalog.get("table_signatures", {})
    else:
        signatures = _table_signatures(db_path, raw)
    previous_signatures = old_catalog.get("table_signatures", {})
    changed_tables = sorted(t for t, signature in signatures.items() if previous_signatures.get(t) != signature)
    removed_tables = sorted(set(previous_signatures) - set(signatures))
    profile_tables = set(changed_tables) | reprofile_tables
    if not old_catalog:
        profile_tables = set(raw)
    prior_profiles = old_catalog.get("profiles", {}) if old_catalog.get("source_hash") else {}
    def profile_changed():
        retained = {t: v for t, v in prior_profiles.items() if t in raw and t not in profile_tables}
        retained.update(profile_database(str(db_path), table_names=profile_tables))
        return retained
    profiles = stage("profile", profile_changed, force=bool(not same_job_input or reprofile_tables), persist=lambda value: _mask(raw, value, sensitive_columns or [])["profiles"])
    profiles = _restore_sensitive_samples(db_path, raw, profiles, set(sensitive_columns or []) | reprofile_due)
    masked = stage("mask", lambda: _mask(raw, profiles, sensitive_columns or []))
    trust = stage("trust_features", lambda: _trust(db_path, raw, profiles))
    joins = stage("join_discovery", lambda: _joins(db_path, raw, profiles))
    desc = stage("descriptions", lambda: _descriptions(raw, descriptions or {}, description_decisions), force=bool(description_decisions), persist=redact_payload)
    metrics = _read(out / "metric_registry.json", [])
    terms = _read(out / "business_terms.json", [])
    golden = _read(out / "golden_store.json", [])
    same_options = previous.get("options_hash") == options_hash
    reindex_tables = set(raw) if not old_catalog or not same_options else set(changed_tables)
    def build_indexes():
        old_index = _read(out / "index_build.json", {})
        if not old_index or not old_catalog or reindex_tables == set(raw):
            return _indexes(db_path, raw, profiles, masked, desc, metrics, terms, golden)
        subset_raw = {table: raw[table] for table in reindex_tables if table in raw}
        subset_profiles = {table: profiles[table] for table in subset_raw}
        subset_masked = {**masked, "masked_columns": [name for name in masked["masked_columns"] if name.split(".", 1)[0] in subset_raw]}
        rebuilt = _indexes(db_path, subset_raw, subset_profiles, subset_masked, desc, metrics, terms, golden)
        retained = []
        for item in old_index.get("keyword", []):
            name = item.get("name", "")
            table = name.split(".", 1)[0] if item.get("kind") == "column" else name if item.get("kind") == "table" else None
            if item.get("kind") in {"table", "column"} and table in raw and table not in reindex_tables:
                retained.append(item)
        global_docs = [item for item in rebuilt["keyword"] if item.get("kind") not in {"table", "column"}]
        keyword = retained + [item for item in rebuilt["keyword"] if item.get("kind") in {"table", "column"}] + global_docs
        values = {name: fields for name, fields in old_index.get("value_index", {}).items()
                  if name.split(".", 1)[0] in raw and name.split(".", 1)[0] not in reindex_tables}
        values.update(rebuilt.get("value_index", {}))
        sensitive = {name for name in old_index.get("sensitive_columns", []) if name.split(".", 1)[0] in raw and name.split(".", 1)[0] not in reindex_tables}
        sensitive.update(rebuilt.get("sensitive_columns", []))
        return {"keyword": keyword, "dense": {"backend": "pending", "documents": keyword},
                "value_index": values, "sensitive_columns": sorted(sensitive)}
    indexes = stage("index_build", build_indexes, force=True,
                    persist=lambda value: _sanitize_index_artifact(db_path, value, masked["masked_columns"]))
    graph = stage("knowledge_graph", lambda: _graph(raw, joins, desc, metrics, terms, trust), persist=redact_payload)
    approved = set(review.get("approved_sensitive_columns", []))
    rejected = set(review.get("rejected_sensitive_columns", []))
    approved_joins = set(review.get("approved_join_ids", []))
    rejected_joins = set(review.get("rejected_join_ids", []))
    for edge in joins:
        decision = review.get("join_decisions", {}).get(edge["id"], {})
        if edge["id"] in rejected_joins or decision.get("status") == "rejected":
            edge["status"] = "rejected"
        elif edge["id"] in approved_joins or decision.get("status") == "approved":
            if edge["status"] == "verified" and decision.get("evidence_hash") == _join_evidence_hash(edge):
                edge["status"] = "approved"
                edge["review"] = decision
            else:
                edge["status"] = "proposed"
                edge["review_invalidated"] = {"reason": "join evidence changed or was not recorded", "previous_decision": decision}
                history = review.setdefault("join_decision_history", {}).setdefault(edge["id"], [])
                if not history or history[-1].get("status") != "invalidated":
                    history.append({"status": "invalidated", "reviewer": "system:refresh", "reviewed_at": datetime.now(timezone.utc).isoformat(), "reason": "evidence changed or missing"})
    graph = _graph(raw, joins, desc, metrics, terms, trust)
    _write(out / "review.json", review)
    _write(out / "knowledge_graph.json", graph)
    discovered_index_masks = set(indexes.get("sensitive_columns", []))
    detected_masks = set(masked["masked_columns"]) | discovered_index_masks
    if discovered_index_masks:
        masked["masked_columns"] = sorted(detected_masks)
        masked["suggestions"] = sorted(set(masked["suggestions"]) | discovered_index_masks)
        _write(out / "mask.json", masked)
    seed_masks = (detected_masks - rejected) | approved
    sensitive_values = _warehouse_sensitive_values(db_path, seed_masks)
    needles = set().union(*(sensitive_variants(v) for v in sensitive_values)) if sensitive_values else set()
    redact = make_redactor(needles)
    desc = _redact_nested(desc, needles, redact)
    graph = _redact_nested(graph, needles, redact)
    _write(out / "descriptions.json", desc)
    _write(out / "knowledge_graph.json", graph)
    cross_masks = set()
    for table, table_profile in profiles.items():
        for col, stats in table_profile["columns"].items():
            qualified = f"{table}.{col}"
            if qualified in seed_masks:
                continue
            values = [*stats.get("sample_values", []), stats.get("min"), stats.get("max")]
            if any(needle.casefold() in str(value).casefold() for value in values if value is not None for needle in needles):
                cross_masks.add(qualified)
                sensitive_values.extend(v for v in values if v is not None)
    cross_masks -= rejected
    needles = set().union(*(sensitive_variants(v) for v in sensitive_values)) if sensitive_values else set()
    pending_mask = [c for c in masked["suggestions"] if c not in approved and c not in rejected]
    pending_mask.extend(c for c in sorted(cross_masks) if c not in approved)
    # Review-approved masks are applied before profiles, prompt documents and indexes are published.
    active_masks = ((set(masked["masked_columns"]) | cross_masks) - rejected) | approved
    sensitive_values = _warehouse_sensitive_values(db_path, active_masks)
    needles = set().union(*(sensitive_variants(v) for v in sensitive_values)) if sensitive_values else set()
    redact = make_redactor(needles)
    desc = _redact_nested(desc, needles, redact)
    graph = _redact_nested(graph, needles, redact)
    _write(out / "descriptions.json", desc)
    _write(out / "knowledge_graph.json", graph)
    for qualified in active_masks:
        table, col = qualified.split(".", 1)
        if table in profiles and col in profiles[table]["columns"]:
            stats = profiles[table]["columns"][col]
            stats["sample_values"] = []
            stats["min"] = None
            stats["max"] = None
            stats["sensitive"] = True
    _write(out / "profile.json", profiles)
    # Redact sensitive literals and their common partial forms from every searchable artifact.
    redact = make_redactor(needles)
    for documents in (indexes["keyword"], indexes.get("dense", {}).get("documents", [])):
        for item in documents:
            item["text"] = redact(item.get("text", ""))
    for qualified in active_masks:
        for item in indexes["keyword"]:
            if item.get("name") == qualified:
                item["text"] = "[MASKED]"
        indexes["value_index"].pop(qualified, None)
    for qualified, values in list(indexes["value_index"].items()):
        indexes["value_index"][qualified] = [v for v in values if not any(needle.casefold() in str(v).casefold() for needle in needles)]
    for qualified in rejected:
        table, col = qualified.split(".", 1)
        if table in raw and col in {c["name"] for c in raw[table]["columns"]}:
            column = next(c for c in raw[table]["columns"] if c["name"] == col)
            entry = {"kind": "column", "name": qualified, "text": f"{qualified} {column['type']}"}
            for documents in (indexes["keyword"], indexes.get("dense", {}).get("documents", [])):
                if not any(item.get("kind") == "column" and item.get("name") == qualified for item in documents):
                    documents.append(entry.copy())
            indexes["value_index"][qualified] = profiles[table]["columns"][col]["sample_values"]
    # Build vectors only after masking and text redaction have been finalized.
    # The stage record makes rebuilds and failures visible and retryable.
    indexes["dense"] = stage("dense_index", lambda: build_dense_payload(indexes["keyword"], previous=previous_dense_index, encoder=dense_encoder), force=True)
    version_inputs = json.dumps({"source_hash": source_hash, "review": review, "metrics": metrics, "terms": terms, "golden": golden}, sort_keys=True, default=str)
    catalog_version = "catalog-" + hashlib.sha256(version_inputs.encode()).hexdigest()[:16]
    # Publish the version with the index first and the catalog last. A reader
    # that observes the new index beside the old catalog fails closed until the
    # catalog commit completes, so an interrupted refresh cannot serve mixed state.
    indexes["catalog_version"] = catalog_version
    _write(out / "index_build.json", indexes)
    _write(out / "join_discovery.json", joins)
    self_test = stage("self_test", lambda: _self_test(raw, indexes, joins, masked, active_masks, sensitive_values, profiles, desc, graph), force=True)
    pending_joins = [j["id"] for j in joins if j["status"] in ("proposed", "verified")]
    needs_review = bool(pending_mask or pending_joins)
    report = {
        "catalog_version": catalog_version, "status": "needs_review" if needs_review else "complete", "source_hash": source_hash,
        "changed_tables": changed_tables, "removed_tables": removed_tables,
        "profiled_tables": sorted(profile_tables), "reindexed_tables": sorted(reindex_tables),
        "table_count": len(raw), "column_count": sum(len(t["columns"]) for t in raw.values()),
        "masked_columns": sorted(active_masks), "sensitive_suggestions_pending": pending_mask,
        "join_counts": {s: sum(j["status"] == s for j in joins) for s in ("verified", "proposed", "approved", "rejected")},
        "stale_copy_tables": [t for t, f in trust.items() if f["likely_stale_copy"]], "warnings": connection_info["warnings"],
        "self_test": self_test, "build_seconds": sum(v.get("duration_seconds", 0) for v in state["stages"].values()),
        "scale": f"{len(raw)} tables", "stages": state["stages"],
        "store": {"type": f"local JSON keyword/value/{indexes['dense']['backend']} dense index", "embedding_model": indexes["dense"]["encoder_version"], "reranker": None},
    }
    _write(out / "catalog.json", {"catalog_version": catalog_version, "source_hash": source_hash, "warehouse_hash": warehouse_hash, "table_signatures": signatures, "tables": raw, "profiles": profiles, "trust": trust, "joins": joins, "descriptions": desc, "graph": graph})
    state["stages"]["report"] = {"status": "complete", "count": 1, "duration_seconds": 0}
    _write(out / "report.json", report)
    state.update({"status": report["status"], "catalog_version": catalog_version, "completed_at": datetime.now(timezone.utc).isoformat(), "dismissed_sensitive_reprofiled": dismissed_sensitive})
    _write(state_path, state)
    # Commit the build as one published generation. This manifest is written
    # last and atomically; readers reject any artifact that does not match it.
    published_artifacts = {}
    for artifact_name in ("connect", "introspect", "profile", "mask", "trust_features",
                          "join_discovery", "descriptions", "index_build", "dense_index",
                          "knowledge_graph", "catalog"):
        artifact_path = out / f"{artifact_name}.json"
        if artifact_path.exists():
            published_artifacts[artifact_path.name] = _hash_file(artifact_path)
    _write(out / "published.json", {
        "catalog_version": catalog_version, "source_hash": source_hash,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "artifacts": published_artifacts,
    })
    return report


def _connect_info(path):
    con = connect_read_only(path)
    try:
        con.execute("SELECT 1").fetchone()
        return {"ok": True, "dialect": "sqlite", "read_only": True, "read_only_verified": True, "warnings": ["SQLite was opened with mode=ro and query_only enabled; external filesystem permissions are not separately audited."]}
    finally:
        con.close()


def _table_signatures(path, raw):
    con = connect_read_only(path)
    try:
        signatures = {}
        for table, info in raw.items():
            qt = _quote(table)
            count = con.execute(f"SELECT COUNT(*) FROM {qt}").fetchone()[0]
            date_col = next((c["name"] for c in info["columns"] if re.search(r"(updated|modified|changed)_at", c["name"], re.I)), None)
            latest = con.execute(f"SELECT MAX({_quote(date_col)}) FROM {qt}").fetchone()[0] if date_col else None
            schema = hashlib.sha256(str(info["ddl"]).encode()).hexdigest()
            content = hashlib.sha256()
            column_names = [column["name"] for column in info["columns"]]
            if column_names:
                try:
                    rows = con.execute(f"SELECT * FROM {qt} ORDER BY rowid")
                except sqlite3.OperationalError:  # WITHOUT ROWID tables need a stable value ordering.
                    order = ", ".join(_quote(name) for name in column_names)
                    rows = con.execute(f"SELECT * FROM {qt} ORDER BY {order}")
                for row in rows:
                    encoded = json.dumps(tuple(row), ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8")
                    content.update(len(encoded).to_bytes(8, "big"))
                    content.update(encoded)
            signatures[table] = hashlib.sha256(f"{schema}|{count}|{latest}|{content.hexdigest()}".encode()).hexdigest()
        return signatures
    finally:
        con.close()


def _introspect(path):
    return inspect_warehouse(str(path))


def _mask(raw, profiles, extra):
    suggested, masked = [], []
    clean = json.loads(json.dumps(profiles, default=str))
    for table, info in raw.items():
        for col in info["columns"]:
            full = f"{table}.{col['name']}"
            stats = clean[table]["columns"][col["name"]]
            if SENSITIVE.search(col["name"]) or full in extra or stats.get("sensitive", False):
                suggested.append(full)
                masked.append(full)
                stats["sample_values"] = []
                stats["min"] = None
                stats["max"] = None
    return {"suggestions": suggested, "masked_columns": masked, "profiles": clean}


def _restore_sensitive_samples(path, raw, profiles, extra):
    """Keep the resumable profile artifact sanitized while reloading masked samples only in memory."""
    con = connect_read_only(path)
    try:
        for table, info in raw.items():
            for column in info["columns"]:
                name = column["name"]
                qualified = f"{table}.{name}"
                if not (SENSITIVE.search(name) or qualified in extra):
                    continue
                stats = profiles.get(table, {}).get("columns", {}).get(name)
                if stats is not None and not stats.get("sample_values"):
                    vals = [row[0] for row in con.execute(f"SELECT DISTINCT {_quote(name)} FROM {_quote(table)} WHERE {_quote(name)} IS NOT NULL LIMIT 5")]
                    stats["sample_values"] = vals
        return profiles
    finally:
        con.close()


def _trust(path, raw, profiles):
    con = connect_read_only(path)
    result = {}
    try:
        for table, profile in profiles.items():
            duplicates = profile["duplicate_key_groups"]
            updated_column = next((column["name"] for column in raw[table]["columns"]
                                   if re.search(r"(^|_)(updated|modified|changed)_at$", column["name"], re.I)), None)
            last_updated, age_days = None, None
            if updated_column:
                last_updated = con.execute(f"SELECT MAX({_quote(updated_column)}) FROM {_quote(table)}").fetchone()[0]
                try:
                    parsed = datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    age_days = max(0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() / 86400)
                except (TypeError, ValueError):
                    age_days = None
            stale_suffix = re.search(r"_(old|backup|archive|copy|snapshot|stale)$", table, re.I)
            stale = bool(stale_suffix or re.search(r"(old|backup|archive|copy|snapshot|stale)", table, re.I))
            stale_target = None
            if stale_suffix:
                base = table[:stale_suffix.start()]
                candidates = [candidate for candidate in raw if candidate != table and not re.search(r"(old|backup|archive|copy|snapshot|stale)", candidate, re.I)]
                candidates.sort(key=lambda candidate: (-SequenceMatcher(None, base.casefold(), candidate.casefold()).ratio(), candidate))
                if candidates and SequenceMatcher(None, base.casefold(), candidates[0].casefold()).ratio() >= 0.6:
                    stale_target = candidates[0]
            result[table] = {"row_count": profile["row_count"], "duplicate_key_groups": duplicates,
                             "duplicate_rate": duplicates / max(1, profile["row_count"]) if duplicates is not None else None,
                             "last_updated": last_updated,
                             "freshness_days": round(age_days, 2) if age_days is not None else None,
                             "freshness": "known" if age_days is not None else "unknown",
                             "historical_query_usage": None, "likely_stale_copy": stale,
                             "likely_stale_copy_of": stale_target}
    finally:
        con.close()
    return result


def _joins(path, raw, profiles):
    con = connect_read_only(path)
    try:
        edges, known = [], set()
        def add(left_t, left_c, right_t, right_c, status, evidence):
            left_cols = [left_c] if isinstance(left_c, str) else list(left_c)
            right_cols = [right_c] if isinstance(right_c, str) else list(right_c)
            key = (left_t, *left_cols, right_t, *right_cols)
            edge_id = hashlib.sha1("|".join(key).encode()).hexdigest()[:12]
            if key not in known:
                known.add(key)
                def unique(table, column):
                    qt = _quote(table)
                    columns = [column] if isinstance(column, str) else column
                    qcols = ", ".join(_quote(c) for c in columns)
                    distinct = con.execute(f"SELECT COUNT(*) FROM (SELECT {qcols} FROM {qt} GROUP BY {qcols})").fetchone()[0]
                    total = profiles[table]["row_count"]
                    nonnull = con.execute(f"SELECT COUNT(*) FROM {qt} WHERE " + " AND ".join(f"{_quote(c)} IS NOT NULL" for c in columns)).fetchone()[0]
                    return nonnull == total and distinct == total
                left_unique = unique(left_t, left_c)
                right_unique = unique(right_t, right_c)
                cardinality = "one_to_one" if left_unique and right_unique else "many_to_one" if right_unique else "one_to_many" if left_unique else "many_to_many"
                left = {"table": left_t, "columns": left_cols}
                right = {"table": right_t, "columns": right_cols}
                if len(left_cols) == 1:
                    left["column"] = left_cols[0]
                    right["column"] = right_cols[0]
                edge = {"id": edge_id, "left": left, "right": right, "cardinality": cardinality, "status": status, "evidence": evidence}
                if cardinality == "many_to_many":
                    edge["warnings"] = ["many_to_many_fanout_risk"]
                if status == "approved" and evidence == "declared_foreign_key":
                    edge["review"] = {"reviewer": "system:declared_foreign_key", "reviewed_at": datetime.now(timezone.utc).isoformat()}
                edges.append(edge)
        for table, info in raw.items():
            groups = {}
            for fk in info["foreign_keys"]:
                groups.setdefault(fk["id"], []).append(fk)
            for fields in groups.values():
                fields.sort(key=lambda fk: fk["sequence"])
                add(table, [fk["column"] for fk in fields], fields[0]["references_table"], [fk["references_column"] for fk in fields], "approved", "declared_foreign_key")
        key_tables = {
            table: [column for column in info["columns"] if column["name"].lower().endswith(("_id", "_key"))]
            for table, info in raw.items()
        }
        key_tables = {table: columns for table, columns in key_tables.items() if columns}
        tables = list(key_tables)
        for i, left in enumerate(tables):
            for right in tables[i + 1:]:
                for lc in key_tables[left]:
                    for rc in key_tables[right]:
                        ln, rn = lc["name"].lower(), rc["name"].lower()
                        similarity = SequenceMatcher(None, ln, rn).ratio()
                        if ln != rn and similarity < .9:
                            continue
                        affinity = lambda value: "integer" if "int" in value.lower() else "text" if any(x in value.lower() for x in ("char", "text", "clob")) else "real" if any(x in value.lower() for x in ("real", "float", "double", "numeric", "decimal")) else value.lower()
                        if affinity(lc["type"]) != affinity(rc["type"]):
                            continue
                        overlap = _value_overlap(con, left, lc["name"], right, rc["name"])
                        if overlap >= .5:
                            left_unique = _column_unique(con, left, lc["name"], profiles[left]["row_count"])
                            right_unique = _column_unique(con, right, rc["name"], profiles[right]["row_count"])
                            left_values = _sample_values(con, left, lc["name"])
                            right_values = _sample_values(con, right, rc["name"])
                            left_containment = len(left_values & right_values) / max(1, len(left_values))
                            right_containment = len(left_values & right_values) / max(1, len(right_values))
                            verified = ((left_unique and right_containment >= .95) or (right_unique and left_containment >= .95))
                            evidence = {"name_similarity": round(similarity, 3), "sample_value_overlap": round(overlap, 3),
                                        "left_unique": left_unique, "right_unique": right_unique,
                                        "left_in_right_containment": round(left_containment, 3),
                                        "right_in_left_containment": round(right_containment, 3),
                                        "type_match": True, "verification_sample_cap": 500}
                            add(left, lc["name"], right, rc["name"], "verified" if verified else "proposed", evidence)
        return edges
    finally:
        con.close()


def _sample_values(connection, table, column, cap=500):
    query = f"SELECT DISTINCT {_quote(column)} FROM {_quote(table)} WHERE {_quote(column)} IS NOT NULL LIMIT ?"
    return {row[0] for row in connection.execute(query, (cap,))}


def _column_unique(connection, table, column, row_count):
    qtable, qcolumn = _quote(table), _quote(column)
    total = connection.execute(f"SELECT COUNT(*) FROM {qtable} WHERE {qcolumn} IS NOT NULL").fetchone()[0]
    distinct = connection.execute(f"SELECT COUNT(DISTINCT {qcolumn}) FROM {qtable}").fetchone()[0]
    return bool(total == row_count and distinct == row_count)


def _join_evidence_hash(edge):
    payload = {key: edge.get(key) for key in ("left", "right", "cardinality", "evidence")}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _descriptions(raw, existing, decisions=None):
    decisions = decisions or {}

    def resolve(key, fallback):
        decision = decisions.get(key) or {}
        status = decision.get("status")
        fallback = fallback.get("text", "") if isinstance(fallback, dict) else str(fallback or "")
        text = str(decision.get("text") or "").strip() if status == "approved" else fallback.strip()
        if status == "rejected":
            return {"text": fallback.strip(), "status": "rejected",
                    "reviewer": decision.get("reviewer"), "reviewed_at": decision.get("reviewed_at")}
        if status == "approved" and text:
            return {"text": text, "status": "approved",
                    "reviewer": decision.get("reviewer"), "reviewed_at": decision.get("reviewed_at")}
        return {"text": text, "status": "draft" if text else "missing"}

    descriptions = {}
    for table, info in raw.items():
        descriptions[table] = resolve(table, existing.get(table, ""))
        descriptions[table]["columns"] = {
            column["name"]: resolve(f"{table}.{column['name']}", "")
            for column in info["columns"]
        }
    return descriptions


def _indexes(db_path, raw, profiles, masked, descriptions, metrics, terms, golden):
    items, values, sensitive_columns = [], {}, set()
    masked_set = set(masked["masked_columns"])
    value_budget = 20000
    con = connect_read_only(db_path)
    try:
        for table, info in raw.items():
            for col in info["columns"]:
                full = f"{table}.{col['name']}"
                if full in masked_set:
                    continue
                profile = masked["profiles"][table]["columns"][col["name"]]
                distinct = profile["distinct_count"]
                if distinct == 0:
                    continue
                if distinct <= 2000 and value_budget > 0:
                    qt, qc = _quote(table), _quote(col["name"])
                    vals = [r[0] for r in con.execute(f"SELECT DISTINCT {qc} FROM {qt} WHERE {qc} IS NOT NULL LIMIT ?", (min(2000, value_budget),))]
                    if any(sensitive_value(value) for value in vals):
                        sensitive_columns.add(full)
                        value_budget -= len(vals)
                        continue
                    values[full] = vals
                    value_budget -= len(vals)
                elif any(word in col["name"].lower() for word in ("name", "title", "label")):
                    samples = profile["sample_values"]
                    if any(sensitive_value(value) for value in samples):
                        sensitive_columns.add(full)
                        continue
                    values[full] = sorted({str(v)[i:i + 3].casefold() for v in samples for i in range(max(0, len(str(v)) - 2))})
    finally:
        con.close()
    for table, info in raw.items():
        description = descriptions[table]
        approved_text = description["text"] if description["status"] == "approved" else ""
        items.append({"kind": "table", "name": table, "text": f"{table} {approved_text}".strip()})
        for col in info["columns"]:
            full = f"{table}.{col['name']}"
            if full in masked_set or full in sensitive_columns:
                continue
            column_description = descriptions[table]["columns"].get(col["name"], {})
            approved_text = column_description.get("text", "") if column_description.get("status") == "approved" else ""
            items.append({"kind": "column", "name": full, "text": f"{full} {col['type']} {approved_text}".strip()})
    for metric in metrics:
        if metric.get("status") == "approved":
            items.append({"kind": "metric", "name": metric["name"], "text": " ".join([metric["name"], *metric.get("synonyms", []), metric["formula"]])})
    for term in terms:
        items.append({"kind": "business_term", "name": term["name"], "synonyms": term.get("synonyms", []), "text": " ".join([term["name"], *term.get("synonyms", [])])})
    for query in golden:
        if query.get("status") == "approved" and query.get("dataset_split") == "development":
            items.append({"kind": "golden_query", "name": query.get("id", query.get("question", "")), "text": query.get("question", "") + " " + query.get("sql", "")})
    return {"keyword": items, "dense": {"backend": "pending", "documents": items}, "value_index": values, "sensitive_columns": sorted(sensitive_columns)}


def _warehouse_sensitive_values(path, masked_set, limit=1000):
    con = connect_read_only(path)
    try:
        values = []
        for qualified in sorted(masked_set):
            table, col = qualified.split(".", 1)
            query = f"SELECT DISTINCT {_quote(col)} FROM {_quote(table)} WHERE {_quote(col)} IS NOT NULL LIMIT ?"
            values.extend(row[0] for row in con.execute(query, (limit,)))
        return values
    finally:
        con.close()


def _sanitize_index_artifact(path, indexes, masked_columns):
    safe = json.loads(json.dumps(indexes, default=str))
    values = _warehouse_sensitive_values(path, set(masked_columns))
    needles = set().union(*(sensitive_variants(v) for v in values)) if values else set()
    redact = make_redactor(needles)
    for documents in (safe["keyword"], safe.get("dense", {}).get("documents", [])):
        for item in documents:
            item["text"] = redact(item.get("text", ""))
    for qualified in set(masked_columns) | set(safe.get("sensitive_columns", [])):
        safe["value_index"].pop(qualified, None)
    for qualified, field_values in list(safe["value_index"].items()):
        safe["value_index"][qualified] = [v for v in field_values if not any(needle.casefold() in str(v).casefold() for needle in needles)]
    return safe


def _redact_nested(value, needles, redact=None):
    redact = redact or make_redactor(needles)
    if isinstance(value, dict):
        return {key: _redact_nested(child, needles, redact) for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_nested(child, needles, redact) for child in value]
    if isinstance(value, str):
        return redact(value)
    return value


def _graph(raw, joins, descriptions, metrics=None, terms=None, trust=None):
    nodes, edges = [], []
    for table, info in raw.items():
        nodes.append({"id": f"table:{table}", "type": "table", "name": table})
        for col in info["columns"]:
            cid = f"column:{table}.{col['name']}"
            nodes.append({"id": cid, "type": "column", "name": col["name"], "data_type": col["type"]})
            edges.append({"type": "belongs_to", "source": cid, "target": f"table:{table}"})
    edges += [{"type": "join", "source": [f"column:{j['left']['table']}.{c}" for c in j['left'].get('columns', [j['left'].get('column')])], "target": [f"column:{j['right']['table']}.{c}" for c in j['right'].get('columns', [j['right'].get('column')])], "status": j["status"], "cardinality": j["cardinality"], "join_id": j["id"]} for j in joins]
    for metric in metrics or []:
        mid = f"metric:{metric['name']}"
        nodes.append({"id": mid, "type": "metric", "name": metric["name"], "status": metric.get("status", "proposed")})
        if metric.get("base_table") in raw:
            edges.append({"type": "metric_uses_table", "source": mid, "target": f"table:{metric['base_table']}"})
            table = metric["base_table"]
            column_refs = set(metric.get("columns", []))
            if metric.get("date_column"):
                column_refs.add(metric["date_column"])
            column_refs.update(re.findall(r"\b[A-Za-z_][\w]*\b", metric.get("formula", "")))
            for reference in column_refs:
                col = reference.split(".")[-1]
                if col in {c["name"] for c in raw[table]["columns"]}:
                    edges.append({"type": "metric_uses_column", "source": mid, "target": f"column:{table}.{col}"})
        for synonym in metric.get("synonyms", []):
            edges.append({"type": "synonym_of", "source": f"term:{synonym}", "target": mid})
    for term in terms or []:
        tid = f"term:{term['name']}"
        nodes.append({"id": tid, "type": "business_term", "name": term["name"]})
        for synonym in term.get("synonyms", []):
            sid = f"term:{synonym}"
            nodes.append({"id": sid, "type": "synonym", "name": synonym})
            edges.append({"type": "synonym_of", "source": sid, "target": tid})
    for table, features in (trust or {}).items():
        if features["likely_stale_copy"] and features.get("likely_stale_copy_of") in raw:
            edges.append({"type": "stale_copy_of", "source": f"table:{table}", "target": f"table:{features['likely_stale_copy_of']}"})
    return {"nodes": nodes, "edges": edges}


def _self_test(raw, indexes, joins, masked, masked_set, sensitive_values, profiles=None, descriptions=None, graph=None):
    table_docs = {i["name"] for i in indexes["keyword"] if i["kind"] == "table"}
    missing = sorted(set(raw) - table_docs)
    leaked = []
    for qualified in masked_set:
        if qualified in indexes["value_index"]:
            leaked.append(qualified)
    serialized = json.dumps({"raw": raw, "profiles": profiles or {}, "indexes": indexes, "mask": masked, "descriptions": descriptions or {}, "graph": graph or {}}, default=str).casefold()
    sensitive_needles = set().union(*(sensitive_variants(value) for value in sensitive_values)) if sensitive_values else set()
    leaked_values = [needle for needle in sensitive_needles if len(needle) >= 4 and needle.casefold() in serialized]
    adjacency = {table: set() for table in raw}
    for edge in joins:
        if edge["status"] != "rejected":
            left, right = edge["left"]["table"], edge["right"]["table"]
            adjacency[left].add(right)
            adjacency[right].add(left)
    pairs, checked, missing_paths = [], 0, []
    for table, neighbors in adjacency.items():
        for neighbor in sorted(neighbors):
            pair = tuple(sorted((table, neighbor)))
            if pair not in pairs:
                pairs.append(pair)
    for start, target in pairs[:20]:
        checked += 1
        seen, todo = {start}, [start]
        while todo and target not in seen:
            current = todo.pop(0)
            for nxt in adjacency[current] - seen:
                seen.add(nxt)
                todo.append(nxt)
        if target not in seen:
            missing_paths.append([start, target])
    passed = not missing and not leaked and not leaked_values and not missing_paths
    return {"passed": passed, "missing_tables": missing, "sensitive_index_leaks": sorted(set(leaked)), "sensitive_value_leak_count": len(leaked_values), "join_path_pairs_checked": checked, "missing_join_paths": missing_paths, "approved_join_edges": sum(j["status"] == "approved" for j in joins)}


def approve_review(output_dir: str | Path, *, approve_joins: list[str] | None = None, reject_joins: list[str] | None = None, approve_sensitive: list[str] | None = None, reject_sensitive: list[str] | None = None, reviewer: str = "unattributed") -> None:
    """Record human decisions in review.json; rerun the build to publish them."""
    if not reviewer.strip() or reviewer.strip().casefold() in {"unattributed", "unknown", "system"}:
        raise ValueError("A named human reviewer is required")
    path = Path(output_dir) / "review.json"
    state = _read(path, {"approved_join_ids": [], "rejected_join_ids": [], "approved_sensitive_columns": [], "rejected_sensitive_columns": []})
    catalog = _read(Path(output_dir) / "catalog.json", {})
    join_by_id = {edge["id"]: edge for edge in catalog.get("joins", [])}
    decisions = (("approved_join_ids", approve_joins, "approved"), ("rejected_join_ids", reject_joins, "rejected"), ("approved_sensitive_columns", approve_sensitive, "approved"), ("rejected_sensitive_columns", reject_sensitive, "rejected"))
    for key, values, status in decisions:
        opposite = "rejected_" + key[len("approved_"):] if key.startswith("approved_") else "approved_" + key[len("rejected_"):]
        state[key] = sorted(set(state.get(key, [])) | set(values or []))
        state[opposite] = sorted(set(state.get(opposite, [])) - set(values or []))
        if "join_ids" in key:
            audit = state.setdefault("join_decisions", {})
            for join_id in values or []:
                if status == "approved":
                    edge = join_by_id.get(join_id)
                    if edge is None or edge.get("status") != "verified":
                        raise ValueError(f"Join {join_id} must have current verified evidence before approval")
                existing = audit.get(join_id)
                if not existing or existing.get("status") != status:
                    record = {"status": status, "reviewer": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat()}
                    if status == "approved":
                        record["evidence_hash"] = _join_evidence_hash(join_by_id[join_id])
                    audit[join_id] = record
                    state.setdefault("join_decision_history", {}).setdefault(join_id, []).append(record.copy())
        elif "sensitive_columns" in key:
            audit = state.setdefault("sensitive_decisions", {})
            for column in values or []:
                existing = audit.get(column)
                if not existing or existing.get("status") != status:
                    audit[column] = {"status": status, "reviewer": reviewer, "reviewed_at": datetime.now(timezone.utc).isoformat()}
    _write(path, state)

def review_descriptions(output_dir: str | Path, *, approve: dict[str, str] | None = None,
                        reject: list[str] | None = None, reviewer: str = "unattributed") -> None:
    """Record draft/approved/rejected description decisions; rerun build to publish."""
    if not reviewer.strip() or reviewer.strip().casefold() in {"unattributed", "unknown", "system"}:
        raise ValueError("A named human reviewer is required")
    path = Path(output_dir) / "review.json"
    state = _read(path, {})
    catalog = _read(Path(output_dir) / "catalog.json", {})
    known_tables = set(catalog.get("tables", {}))
    decisions = state.setdefault("description_decisions", {})
    history = state.setdefault("description_decision_history", {})
    for key, text in (approve or {}).items():
        key, text = key.strip(), str(text or "").strip()
        if not key or not text:
            raise ValueError("Approved descriptions require a target and non-empty text")
        if known_tables and key.split(".", 1)[0] not in known_tables:
            raise ValueError(f"Unknown description target: {key}")
        record = {"status": "approved", "text": text, "reviewer": reviewer.strip(),
                  "reviewed_at": datetime.now(timezone.utc).isoformat()}
        decisions[key] = record
        history.setdefault(key, []).append(record.copy())
    for key in reject or []:
        key = key.strip()
        if not key:
            raise ValueError("Rejected descriptions require a target")
        if known_tables and key.split(".", 1)[0] not in known_tables:
            raise ValueError(f"Unknown description target: {key}")
        record = {"status": "rejected", "reviewer": reviewer.strip(),
                  "reviewed_at": datetime.now(timezone.utc).isoformat()}
        decisions[key] = record
        history.setdefault(key, []).append(record.copy())
    _write(path, state)
