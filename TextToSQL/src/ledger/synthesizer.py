"""Ledger-grounded response synthesis with a deterministic fallback."""
from __future__ import annotations

from .evidence import EvidenceLedger, FactChecker


class Synthesizer:
    def __init__(self, fact_checker: FactChecker | None = None):
        self.fact_checker = fact_checker or FactChecker()

    def synthesize(self, ledger: EvidenceLedger, *, llm=None, driver_analysis: bool = False) -> dict:
        fallback = ledger.render(driver_analysis=driver_analysis)
        if llm is None:
            return {"text": fallback, "source": "template", "fact_check": self.fact_checker.verify(fallback, ledger, driver_analysis=driver_analysis)}
        prompt = "Write a concise answer using only the provided evidence claims. Preserve their figures, units, meaning and limits. Add no facts."
        evidence = "\n".join(f"CLAIM: {item['claim']} | GRADE: {item['grade']} | LIMITS: {item.get('limits') or ''}" for item in ledger.claims)
        try:
            result = llm.chat("Evidence-grounded answer writer.", prompt + "\n\n" + evidence)
            text = result.text
            checked = self.fact_checker.verify(text, ledger, driver_analysis=driver_analysis)
            if checked["passed"]:
                return {"text": text, "source": "model", "fact_check": checked}
        except Exception:
            pass
        checked = self.fact_checker.verify(fallback, ledger, driver_analysis=driver_analysis)
        return {"text": fallback, "source": "template", "fact_check": checked}
