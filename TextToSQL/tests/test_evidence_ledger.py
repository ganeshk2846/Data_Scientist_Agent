from types import SimpleNamespace

import pytest

from src.ledger.evidence import E5_NOTE, EvidenceLedger, FactChecker
from src.ledger.synthesizer import Synthesizer


def test_supported_and_unsupported_causal_and_numeric_claims_include_spans():
    ledger = EvidenceLedger()
    ledger.add("Revenue was 1,234.50 dollars.", query_id="query-1", grade=3)
    checker = FactChecker()
    assert checker.verify("Revenue was $1,234.5.", ledger)["passed"]
    assert checker.verify("Revenue was 1,235 dollars.", ledger)["passed"]  # nearest dollar rounding
    result = checker.verify("Revenue was 1,500 dollars.", ledger)
    assert not result["passed"]
    assert result["issues"][0]["kind"] == "unsupported_number"
    assert result["issues"][0]["span"] == {"start": 0, "end": len("Revenue was 1,500 dollars.")}
    causal = checker.verify("Revenue grew because of the campaign.", ledger)
    assert not causal["passed"]
    assert {issue["kind"] for issue in causal["issues"]} >= {"unsupported_claim", "unsupported_causal_language"}


def test_number_words_ranges_percentages_units_and_thousands_separators():
    ledger = EvidenceLedger()
    ledger.add("Between 1,000 and 1,200 orders were processed, a 25 percent increase.", artifact="query-results.json", grade=3)
    checker = FactChecker()
    assert checker.verify("Between one thousand and twelve hundred orders were processed, a 25% increase.", ledger)["passed"]
    assert not checker.verify("Between one thousand and thirteen hundred orders were processed, a 25% increase.", ledger)["passed"]
    assert not checker.verify("There were 25 customers.", ledger)["passed"]


@pytest.mark.parametrize("phrase", ["caused", "because of", "due to", "led to", "driven by", "resulted in", "responsible for"])
def test_all_causal_phrases_require_grade_four_and_attached_limits(phrase):
    ledger = EvidenceLedger()
    ledger.add(f"Campaign {phrase} revenue growth of 12.5 percent.", query_id="q-causal", grade=4, limits="This is an observational association.")
    text = ledger.synthesize(driver_analysis=True)
    assert "Limits: This is an observational association." in text
    assert E5_NOTE in text
    assert FactChecker().verify(text, ledger, driver_analysis=True)["passed"]
    assert not FactChecker().verify(f"Campaign {phrase} revenue growth of 12.5 percent.", ledger)["passed"]


def test_ledger_requires_evidence_reference_and_synthesizer_uses_fallback():
    ledger = EvidenceLedger()
    with pytest.raises(ValueError):
        ledger.add("Sales were 5.", grade=2)
    ledger.add("Sales were 5.", artifact="sales-query.json", grade=2)

    class FakeLLM:
        def __init__(self, text=None, fail=False):
            self.text, self.fail, self.prompts = text, fail, []

        def chat(self, system, user):
            self.prompts.append((system, user))
            if self.fail:
                raise TimeoutError("fake timeout")
            return SimpleNamespace(text=self.text)

    fabricated = Synthesizer().synthesize(ledger, llm=FakeLLM("Sales were 500."))
    assert fabricated["source"] == "template"
    assert fabricated["text"] == "Sales were 5."
    timed_out = Synthesizer().synthesize(ledger, llm=FakeLLM(fail=True))
    assert timed_out["source"] == "template"


def test_evidence_grade_contract_is_zero_through_four():
    ledger = EvidenceLedger()
    assert ledger.add("Observed 2 orders.", query_id="q0", grade=0)["grade"] == 0
    assert ledger.add("Trend caused 2 orders.", query_id="q4", grade=4)["grade"] == 4
    with pytest.raises(ValueError, match="0 to 4"):
        ledger.add("Unsupported grade.", query_id="q5", grade=5)


def test_fifty_labelled_adversarial_number_cases_report_precision_recall():
    cases = []
    for number in range(100, 125):
        cases.append({"id": f"supported-{number}", "label": "supported", "claim": f"Metric was {number} units.", "answer": f"Metric was {number} units.", "reject": False})
        cases.append({"id": f"fabricated-{number}", "label": "fabricated", "claim": f"Metric was {number} units.", "answer": f"Metric was {number + 1000} units.", "reject": True})
    assert len(cases) == 50
    tp = fp = fn = tn = 0
    for case in cases:
        ledger = EvidenceLedger()
        ledger.add(case["claim"], query_id=case["id"], grade=2)
        predicted_reject = not FactChecker().verify(case["answer"], ledger)["passed"]
        if case["reject"] and predicted_reject:
            tp += 1
        elif case["reject"]:
            fn += 1
        elif predicted_reject:
            fp += 1
        else:
            tn += 1
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    assert (tp, fp, fn, tn) == (25, 0, 0, 25)
    assert precision == recall == 1.0


def test_fact_checker_rejects_unsupported_dates_and_accepts_equivalent_formats():
    ledger = EvidenceLedger()
    ledger.add("Revenue was recorded on 2025-03-04.", query_id="q-date", grade=2)
    checker = FactChecker()
    assert checker.verify("Revenue was recorded on March 4, 2025.", ledger)["passed"]
    result = checker.verify("Revenue was recorded on March 5, 2025.", ledger)
    assert not result["passed"]
    assert "unsupported_date" in {issue["kind"] for issue in result["issues"]}


@pytest.mark.parametrize("written_date", [
    "2025/03/04", "20250304", "04 March 2025", "March 4th, 2025",
    "03/04/2025", "04.03.2025",
])
def test_fact_checker_accepts_additional_common_date_formats(written_date):
    ledger = EvidenceLedger()
    ledger.add("Revenue was recorded on 2025-03-04.", query_id="date-format", grade=2)
    result = FactChecker().verify(f"Revenue was recorded on {written_date}.", ledger)
    assert result["passed"], result["issues"]


def test_fact_checker_accepts_day_first_date_when_day_exceeds_twelve():
    ledger = EvidenceLedger()
    ledger.add("Revenue was recorded on 2025-12-31.", query_id="date-day-first", grade=2)
    result = FactChecker().verify("Revenue was recorded on 31/12/2025.", ledger)
    assert result["passed"], result["issues"]


def test_fact_checker_accepts_abbreviated_september_date():
    ledger = EvidenceLedger()
    ledger.add("Revenue was recorded on 2025-09-04.", query_id="date-sept", grade=2)
    result = FactChecker().verify("Revenue was recorded on 4 Sept 2025.", ledger)
    assert result["passed"], result["issues"]


def test_fact_checker_requires_linked_valid_grade_for_numeric_claims():
    ungraded = [{"claim": "Revenue was 5 dollars.", "query_id": "q-ungraded"}]
    result = FactChecker().verify("Revenue was 5 dollars.", ungraded)
    assert not result["passed"]
    assert "unsupported_claim" in {issue["kind"] for issue in result["issues"]}
    assert "unsupported_number" in {issue["kind"] for issue in result["issues"]}


def test_e5_note_check_is_case_insensitive_but_still_mandatory():
    ledger = EvidenceLedger()
    ledger.add("Observed revenue increased.", query_id="q-driver", grade=2)
    note = E5_NOTE.upper()
    result = FactChecker().verify(f"Observed revenue increased. {note}", ledger, driver_analysis=True)
    assert result["passed"]
    missing = FactChecker().verify("Observed revenue increased.", ledger, driver_analysis=True)
    assert "missing_causal_boundary_note" in {issue["kind"] for issue in missing["issues"]}
