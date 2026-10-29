"""BE-2 approval and feedback controls (MET-1/6, OPS-8/9, DATA-8)."""
import json
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pytest

from src.knowledge.stores import ActionLibrary, FeedbackStore, GoldenStore, MetricRegistry, TraceStore
from data_gen.evaluation import run_final_evaluation
from data_gen.splits import QuestionSplitStore
from data_gen.access import ScoringAccessPolicy


def metric(formula="SUM(amount)"):
    return {"name": "revenue", "synonyms": ["sales"], "formula": formula,
            "required_filters": [], "grain": ["month"], "date_column": "created_at",
            "allowed_dimensions": [], "base_table": "orders", "join_path": [],
            "caveats": [], "reconciliation_values": {}}


def _propose_metric_in_process(path):
    return MetricRegistry(path).propose(metric())["version"]


def test_metric_changes_require_named_approval_and_keep_revision_history(tmp_path):
    registry = MetricRegistry(tmp_path / "metrics.json")
    first = registry.propose(metric())
    with pytest.raises(ValueError, match="reviewer"):
        registry.decide(first["id"], approve=True)
    with pytest.raises(PermissionError, match="not authorized"):
        registry.decide(first["id"], approve=True, reviewer="reviewer-1", note="checked")
    registry = MetricRegistry(registry.path, reviewer_authorizer=lambda identity: identity == "reviewer-1")
    registry.decide(first["id"], approve=True, reviewer="reviewer-1", note="checked")
    assert registry.approved()[0]["version"] == 1
    assert registry.resolve("sales")["id"] == first["id"]
    second = registry.propose(metric("SUM(net_amount)"))
    assert second["version"] == 2 and second["status"] == "proposed"
    assert registry.approved() == []
    with pytest.raises(ValueError, match="Only proposed"):
        registry.decide(first["id"], approve=False, reviewer="reviewer-1", version=1,
                        note="attempted duplicate transition")


def test_metric_review_denies_unknown_identity_duplicate_and_invalid_transition(tmp_path):
    path = tmp_path / "metrics.json"
    registry = MetricRegistry(path, reviewer_authorizer=lambda identity: identity == "authorized-reviewer")
    proposal = registry.propose(metric())
    with pytest.raises(PermissionError, match="not authorized"):
        registry.decide(proposal["id"], approve=True, reviewer="untrusted", note="looks good")
    with pytest.raises(ValueError, match="reason"):
        registry.decide(proposal["id"], approve=False, reviewer="authorized-reviewer")
    with pytest.raises(ValueError, match="boolean"):
        registry.decide(proposal["id"], approve="yes", reviewer="authorized-reviewer", note="invalid")
    registry.decide(proposal["id"], approve=False, reviewer="authorized-reviewer", note="not valid")
    with pytest.raises(ValueError, match="Only proposed"):
        registry.decide(proposal["id"], approve=True, reviewer="authorized-reviewer", note="duplicate")
    decision = json.loads(path.read_text(encoding="utf-8"))[0]["decision_history"][-1]
    assert decision["status"] == "rejected"
    assert decision["reviewer"] == "authorized-reviewer"
    assert decision["authorization"] == "authorized_by_host_policy"


def test_metric_reviewer_policy_requires_boolean_authorization_and_redacts_notes(tmp_path):
    path = tmp_path / "metrics.json"
    proposal = MetricRegistry(path).propose(metric())
    weak_policy = MetricRegistry(path, reviewer_authorizer=lambda identity: "yes")
    with pytest.raises(PermissionError):
        weak_policy.decide(proposal["id"], approve=True, reviewer="reviewer", note="ok")
    policy = MetricRegistry(path, reviewer_authorizer=lambda identity: True)
    policy.decide(proposal["id"], approve=True, reviewer="reviewer", note="contact person@example.invalid")
    decision = json.loads(path.read_text(encoding="utf-8"))[0]["decision_history"][-1]
    assert "person@example.invalid" not in json.dumps(decision)


def test_metric_proposals_reject_malformed_contract_fields(tmp_path):
    registry = MetricRegistry(tmp_path / "metrics.json")
    with pytest.raises(ValueError, match="synonyms"):
        registry.propose({**metric(), "synonyms": [None]})
    with pytest.raises(ValueError, match="join_path"):
        registry.propose({**metric(), "join_path": "orders->customers"})


def test_concurrent_metric_proposals_keep_every_revision(tmp_path):
    registry = MetricRegistry(tmp_path / "metrics.json")
    with ThreadPoolExecutor(max_workers=8) as workers:
        revisions = list(workers.map(lambda _: registry.propose(metric()), range(20)))
    assert sorted(item["version"] for item in revisions) == list(range(1, 21))
    persisted = json.loads(registry.path.read_text(encoding="utf-8"))
    assert sorted(item["version"] for item in persisted) == list(range(1, 21))


def test_cross_process_metric_proposals_keep_every_revision(tmp_path):
    path = str(tmp_path / "metrics.json")
    with ProcessPoolExecutor(max_workers=4) as workers:
        revisions = list(workers.map(_propose_metric_in_process, [path] * 12))
    assert sorted(revisions) == list(range(1, 13))
    persisted = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert sorted(item["version"] for item in persisted) == list(range(1, 13))


def test_golden_promotion_requires_checks_human_and_no_heldout_leakage(tmp_path):
    store = GoldenStore(tmp_path / "golden.json")
    record = {"question": "revenue by month", "sql": "SELECT 1", "id": "g1"}
    with pytest.raises(ValueError, match="result checks"):
        store.promote(record, result_checks_passed=False, human_approved=True, reviewer="lead")
    with pytest.raises(ValueError, match="held-out question set"):
        store.promote(record, result_checks_passed=True, human_approved=True, reviewer="lead")
    with pytest.raises(ValueError, match="leakage"):
        store.promote(record, result_checks_passed=True, human_approved=True, reviewer="lead",
                      heldout_questions=["show revenue by month"])
    assert store.leakage_check([])["passed"]
    store.promote(record, result_checks_passed=True, human_approved=True, reviewer="lead",
                  heldout_questions=["show order counts by region"])
    assert store.assert_final_run_safe(["show order counts by region"])["passed"]
    with pytest.raises(ValueError, match="Final evaluation blocked"):
        store.assert_final_run_safe(["revenue by month"])


def test_golden_candidate_requires_each_check_and_person_decision(tmp_path):
    store = GoldenStore(tmp_path / "golden.json")
    candidate_id = store.propose("total shipments", "SELECT COUNT(*) FROM shipments", "run-1",
                                 [{"name": "result_check", "passed": True}], catalog_version="catalog-1")
    with pytest.raises(ValueError, match="held-out question set"):
        store.decide(candidate_id, approve=True, reviewer="reviewer", result_checks_passed=True)
    store.decide(candidate_id, approve=True, reviewer="reviewer", result_checks_passed=True,
                 heldout_questions=["count shipments by month"])
    assert store.nearest("total shipments", k=1)[0]["entry_id"] == candidate_id

    blocked = store.propose("customer churn by age", "SELECT 1", "run-2",
                            [{"name": "result_check", "passed": False}])
    with pytest.raises(ValueError, match="passing result checks"):
        store.decide(blocked, approve=True, reviewer="reviewer", result_checks_passed=True)

    rejected = store.propose("monthly cancellations", "SELECT 0", "run-3",
                             [{"name": "result_check", "passed": False}])
    with pytest.raises(ValueError, match="rejection reason"):
        store.decide(rejected, approve=False, reviewer="reviewer", result_checks_passed=False)
    store.decide(rejected, approve=False, reviewer="reviewer", result_checks_passed=False,
                 rejection_reason="Result did not match the reviewed reference output.")
    record = next(item for item in json.loads(store.path.read_text(encoding="utf-8"))
                  if item["entry_id"] == rejected)
    assert record["status"] == "rejected"
    assert record["reviewed_by"] == "reviewer"
    assert record["rejection_reason"] == "Result did not match the reviewed reference output."


def test_golden_heldout_material_cannot_be_promoted_or_retrieved(tmp_path):
    store = GoldenStore(tmp_path / "golden.json")
    with pytest.raises(ValueError, match="Only development-set"):
        store.promote({"question": "held-out question", "sql": "SELECT 1"},
                      result_checks_passed=True, human_approved=True, reviewer="reviewer",
                      dataset_split="held-out", heldout_questions=["unrelated question"])
    store.path.write_text(json.dumps([{"entry_id": "hold", "question": "held-out question",
                                       "dataset_split": "held-out", "status": "approved"}]), encoding="utf-8")
    assert store.nearest("held-out question") == []
    store.path.write_text(json.dumps([{"entry_id": "candidate", "question": "held-out question",
                                       "dataset_split": "held-out", "status": "proposed",
                                       "checks": [{"passed": True}]}]), encoding="utf-8")
    with pytest.raises(ValueError, match="Only development-set"):
        store.decide("candidate", approve=True, reviewer="reviewer", result_checks_passed=True,
                     heldout_questions=["unrelated question"])


def test_feedback_is_redacted_development_only_and_requires_dev_evaluation(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")
    with pytest.raises(ValueError, match="development"):
        store.append({"run_id": "r1", "correction": "wrong", "dataset_split": "held-out"})
    store.append({"run_id": "r1", "correction": "email person@example.invalid should not leak", "dataset_split": "development"})
    with pytest.raises(ValueError, match="development"):
        store.record_evaluation(["r1"], split="held-out", passed=True, reviewer="reviewer")
    store.record_evaluation(["r1"], split="development", passed=True, reviewer="reviewer")
    assert store.list_pending() == []
    assert "person@example.invalid" not in (tmp_path / "feedback.json").read_text(encoding="utf-8")


def test_trace_store_and_action_library_expose_expected_read_interfaces(tmp_path):
    traces = TraceStore(tmp_path / "traces.json")
    traces.write({"run_id": "r1", "prompt": "person@example.invalid", "step": "query"})
    assert traces.get("r1")[0]["prompt"] == "[REDACTED]"
    actions = ActionLibrary(tmp_path / "actions.json")
    actions.put("a1", {"title": "Call", "driver_types": ["decline", "churn"]})
    assert actions.match(["churn"])[0]["title"] == "Call"


def test_trace_redaction_preserves_canonical_run_id_when_sensitive_digits_overlap(tmp_path):
    traces = TraceStore(tmp_path / "traces.json")
    run_id = "00000000-0000-0000-0000-000000003210"
    traces.write({"run_id": run_id, "input": "call +1 555 123 3210"})
    assert len(traces.get(run_id)) == 1
    content = json.loads(traces.path.read_text(encoding="utf-8"))
    assert content[0]["run_id"] == run_id
    assert "555 123 3210" not in content[0]["input"]


def test_final_evaluation_checks_leakage_before_calling_scorer(tmp_path):
    questions = QuestionSplitStore(tmp_path / "questions.json")
    questions.create([{"id": "hold-1", "split": "held-out", "question": "revenue by month"}])
    golden = GoldenStore(tmp_path / "golden.json")
    # Simulate an older approved record written before promotion required the
    # held-out comparison set; the final gate must reject it before scoring.
    golden.path.write_text(json.dumps([{"entry_id": "g1", "question": "revenue by month", "sql": "SELECT 1",
                                        "status": "approved", "dataset_split": "development"}]), encoding="utf-8")
    called = []
    with pytest.raises(ValueError, match="leakage"):
        run_final_evaluation(questions, golden, lambda case: called.append(case),
                             principal="test-scorer", scoring_policy=ScoringAccessPolicy(["test-scorer"]))
    assert called == []


def test_final_evaluation_denies_missing_or_untrusted_scoring_principal(tmp_path):
    questions = QuestionSplitStore(tmp_path / "questions.json")
    questions.create([{"id": "hold-1", "split": "held-out", "question": "private question"}])
    golden = GoldenStore(tmp_path / "golden.json")
    called = []
    with pytest.raises(PermissionError):
        run_final_evaluation(questions, golden, lambda case: called.append(case), principal="test-scorer")
    with pytest.raises(PermissionError):
        run_final_evaluation(questions, golden, lambda case: called.append(case), principal="agent",
                             scoring_policy=ScoringAccessPolicy(["test-scorer"]))
    assert called == []


def test_heldout_scoring_cannot_write_development_trace_or_metric_stores(tmp_path):
    questions = QuestionSplitStore(tmp_path / "questions.json")
    questions.create([{"id": "hold-1", "split": "held-out", "question": "private evaluation question"}])
    golden = GoldenStore(tmp_path / "golden.json")
    traces = TraceStore(tmp_path / "traces.json")
    registry = MetricRegistry(tmp_path / "metrics.json", reviewer_authorizer=lambda _: True)
    proposal = registry.propose(metric())

    def score(case):
        assert case["question"] == "private evaluation question"
        traces.write({"run_id": "heldout", "input": case["question"]})
        return {"score": 1}

    with pytest.raises(PermissionError, match="held-out scoring"):
        run_final_evaluation(questions, golden, score, principal="test-scorer",
                             scoring_policy=ScoringAccessPolicy(["test-scorer"]))
    assert not traces.path.exists()
    with pytest.raises(PermissionError, match="held-out scoring"):
        from data_gen.access import heldout_scoring_scope
        with heldout_scoring_scope():
            registry.decide(proposal["id"], approve=True, reviewer="reviewer", note="should be blocked")
    assert registry.get(proposal["id"])["status"] == "proposed"
