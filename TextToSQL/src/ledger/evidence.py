"""Evidence Ledger and conservative deterministic synthesis checks."""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

CAUSAL = re.compile(r"\b(caused?|because\s+of|due\s+to|led\s+to|driven\s+by|resulted\s+in|responsible\s+for)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])(?P<currency>[$€£₹])?\s*(?P<value>-?\d[\d,]*(?:\.\d+)?)(?:\s*(?P<scale>thousand|million|billion))?\s*(?P<unit>%|percent(?:age)?|units?|people|customers?|orders?|dollars?|usd|eur|gbp|rupees?|hours?|days?|weeks?|months?|years?|km|miles?|kg|tons?)?(?![A-Za-z0-9_])", re.I)
WORD_NUMBER = re.compile(r"(?<!\w)(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion)(?:[ -]+(?:and[ -]+)?(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|million|billion))*(?!\w)", re.I)
E5_NOTE = "Causal-boundary note (E5): observed relationships are descriptive and do not establish causation."
MONTH = r"(?:January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|August|Aug|September|Sep|Sept|October|Oct|November|Nov|December|Dec)"
DATE = re.compile(
    rf"(?<!\w)(?:\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}|"
    rf"\d{{1,2}}[-/.]\d{{1,2}}[-/.]\d{{2,4}}|\d{{8}}|"
    rf"{MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?[,]?\s+\d{{4}}|"
    rf"\d{{1,2}}(?:st|nd|rd|th)?\s+{MONTH}[,]?\s+\d{{4}})(?!\w)", re.I)
STOP = {"a", "an", "the", "is", "are", "was", "were", "be", "been", "being", "of", "to", "for", "in", "on", "by", "from", "with", "and", "or", "as", "at", "it", "this", "that", "these", "those", "shows", "show", "reported", "was", "were"}
SYNONYMS = {"rose": "increase", "risen": "increase", "increased": "increase", "increases": "increase", "grew": "increase", "growth": "increase", "fell": "decrease", "declined": "decrease", "decreased": "decrease", "dropped": "decrease", "totaled": "total", "totals": "total", "amount": "total"}
NUMBER_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}


class EvidenceLedger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.claims = json.loads(self.path.read_text(encoding="utf-8")) if self.path and self.path.exists() else []

    def add(self, claim: str, *, query_id: str | None = None, artifact: str | None = None, grade: int, limits: str | None = None) -> dict:
        if not query_id and not artifact:
            raise ValueError("Each ledger claim must link to a query_id or module artifact")
        if grade not in range(0, 5):
            raise ValueError("Evidence grade must be from 0 to 4")
        item = {"number": len(self.claims) + 1, "claim": claim, "query_id": query_id, "artifact": artifact, "grade": grade, "limits": limits}
        self.claims.append(item)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.claims, indent=2), encoding="utf-8")
        return item

    def render(self, claim_numbers: list[int] | None = None, *, driver_analysis: bool = False) -> str:
        selected = [c for c in self.claims if (claim_numbers is None or c.get("number") in claim_numbers) and (c.get("query_id") or c.get("artifact"))]
        sentences = []
        for claim in selected:
            sentence = claim["claim"]
            if CAUSAL.search(sentence) and claim.get("grade") == 4 and claim.get("limits"):
                sentence = sentence.rstrip(" .!? ") + f" (Limits: {claim['limits']})."
            sentences.append(sentence)
        text = " ".join(sentences) or "The available evidence does not support a numeric conclusion."
        if driver_analysis and E5_NOTE not in text:
            text += " " + E5_NOTE
        return text

    def check(self, text: str, *, driver_analysis: bool = False) -> dict:
        return FactChecker().verify(text, self, driver_analysis=driver_analysis)

    def synthesize(self, claim_numbers: list[int] | None = None, *, driver_analysis: bool = False) -> str:
        text = self.render(claim_numbers, driver_analysis=driver_analysis)
        result = self.check(text, driver_analysis=driver_analysis)
        if not result["passed"]:
            raise ValueError(f"Evidence check failed: {result['issues']}")
        return text


def _word_value(phrase: str) -> Decimal:
    total, group = 0, 0
    for word in re.findall(r"[a-z]+", phrase.lower()):
        if word == "and":
            continue
        if word in NUMBER_WORDS:
            group += NUMBER_WORDS[word]
        elif word == "hundred":
            group = max(1, group) * 100
        elif word in ("thousand", "million", "billion"):
            scale = {"thousand": 1000, "million": 1000000, "billion": 1000000000}[word]
            total += max(1, group) * scale
            group = 0
    return Decimal(total + group)


def _word_quantities(phrase: str) -> list[Decimal]:
    pieces = re.split(r"\s+and\s+", phrase, flags=re.I)
    if len(pieces) > 1 and re.search(r"\b(?:thousand|million|billion)\b", pieces[0], re.I) and re.search(r"\bhundred\b", pieces[-1], re.I):
        return [_word_value(piece) for piece in pieces]
    return [_word_value(phrase)]


def _quantities(text: str):
    # Calendar dates are checked as dates, not as three unrelated numbers.
    text = DATE.sub(lambda match: " " * len(match.group(0)), text)
    found = []
    covered = []
    matches = list(NUMBER.finditer(text))
    for index, match in enumerate(matches):
        try:
            value = Decimal(match.group("value").replace(",", ""))
        except InvalidOperation:
            continue
        scale = match.group("scale")
        if scale:
            value *= Decimal({"thousand": 1000, "million": 1000000, "billion": 1000000000}[scale.lower()])
        unit = (match.group("unit") or "").lower()
        if not unit and index + 1 < len(matches):
            following = matches[index + 1]
            separator = text[match.end():following.start()]
            if re.fullmatch(r"\s*(?:and|to|through|[-–])\s*", separator, re.I):
                unit = (following.group("unit") or "").lower()
        if match.group("currency"):
            unit = {"$": "currency", "€": "currency", "£": "currency", "₹": "currency"}[match.group("currency")]
        elif unit in ("dollar", "dollars", "usd", "eur", "gbp", "rupee", "rupees"):
            unit = "currency"
        elif unit in ("percent", "percentage", "%"):
            unit = "percent"
        elif unit.endswith("s"):
            unit = unit[:-1]
        found.append((value, unit, len(match.group("value").split(".")[-1]) if "." in match.group("value") else 0))
        covered.append(match.span())
    for match in WORD_NUMBER.finditer(text):
        if any(a <= match.start() < b for a, b in covered):
            continue
        phrase = match.group(0)
        unit_match = re.match(r"\s*(percent(?:age)?|people|customers?|orders?|dollars?|hours?|days?|weeks?|months?|years?|km|miles?|kg|tons?)\b", text[match.end():], re.I)
        unit = unit_match.group(1).lower() if unit_match else ""
        if unit in ("percent", "percentage"):
            unit = "percent"
        elif unit in ("dollar", "dollars"):
            unit = "currency"
        elif unit.endswith("s"):
            unit = unit[:-1]
        for word_value in _word_quantities(phrase):
            found.append((word_value, unit, 0))
    return found


def _dates(text: str) -> list[date]:
    parsed = []
    for match in DATE.finditer(text):
        value = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", match.group(0), flags=re.I)
        candidates: list[date] = []
        if re.fullmatch(r"\d{8}", value):
            formats = ("%Y%m%d",)
        elif re.match(r"^\d{4}[-/.]", value):
            normalized = re.sub(r"[-/]", ".", value)
            formats = ("%Y.%m.%d", "%Y.%d.%m")
            value = normalized
        elif re.search(r"[A-Za-z]", value):
            normalized = re.sub(r"\s+", " ", value.replace(",", " ")).strip()
            normalized = re.sub(r"\bSept\b", "Sep", normalized, flags=re.I)
            formats = ("%B %d %Y", "%b %d %Y", "%d %B %Y", "%d %b %Y")
            value = normalized
        else:
            normalized = re.sub(r"[-/.]", "/", value)
            parts = normalized.split("/")
            formats = ("%d/%m/%Y", "%d/%m/%y", "%m/%d/%Y", "%m/%d/%y")
            if len(parts[0]) == 4:
                formats = ("%Y/%m/%d", "%Y/%d/%m")
            value = normalized
        for fmt in formats:
            try:
                candidate = datetime.strptime(value, fmt).date()
            except ValueError:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
            # An ambiguous numeric date can validly mean either convention;
            # retaining both avoids rejecting equivalent day-first evidence.
            if len(candidates) == 2:
                break
        parsed.extend(candidates)
    return parsed


def _tokens(text: str):
    tokens = set()
    text = DATE.sub(" ", text or "")
    for token in re.findall(r"[a-z]+", text.casefold()):
        if token in STOP or token in NUMBER_WORDS or token in {"hundred", "thousand", "million", "billion"}:
            continue
        token = SYNONYMS.get(token, token)
        if token.endswith("s") and len(token) > 3:
            token = token[:-1]
        tokens.add(token)
    return tokens


class FactChecker:
    """Conservative claim checker returning exact sentence spans for violations."""

    def verify(self, text: str, ledger: EvidenceLedger | list[dict], *, driver_analysis: bool = False) -> dict:
        claims = ledger.claims if isinstance(ledger, EvidenceLedger) else ledger
        valid_claims = [c for c in claims if (c.get("query_id") or c.get("artifact")) and c.get("claim") and isinstance(c.get("grade"), int) and c.get("grade") in range(5)]
        evidence_numbers = [q for claim in valid_claims for q in _quantities(claim["claim"])]
        evidence_dates = [d for claim in valid_claims for d in _dates(claim["claim"])]
        issues = []
        if not text.strip():
            return {"passed": False, "issues": [{"kind": "empty_answer", "sentence": "", "span": {"start": 0, "end": 0}}]}
        for match in re.finditer(r"\S.*?(?:(?<=[.!?])\s+|$)", text, re.S):
            raw = match.group(0)
            leading = len(raw) - len(raw.lstrip())
            sentence = raw.strip()
            start, end = match.start() + leading, match.start() + len(raw.rstrip())
            if not sentence:
                continue
            normalized_sentence = sentence.casefold()
            if normalized_sentence == "the available evidence does not support a numeric conclusion." or normalized_sentence == E5_NOTE.casefold():
                continue
            sentence_claims = []
            sentence_tokens = _tokens(sentence)
            for claim in valid_claims:
                evidence_tokens = _tokens(claim["claim"])
                allowed = evidence_tokens | _tokens(claim.get("limits", "")) | {"limit", "limits"}
                if sentence_tokens <= allowed:
                    sentence_claims.append(claim)
            if sentence_tokens and not sentence_claims:
                issues.append({"kind": "unsupported_claim", "sentence": sentence, "span": {"start": start, "end": end}})
            for quantity in _quantities(sentence):
                value, unit, precision = quantity
                matches = [e for e in evidence_numbers if e[1] == unit and abs(value - e[0]) <= Decimal("0.5") * (Decimal(10) ** -precision)]
                if not matches:
                    issues.append({"kind": "unsupported_number", "sentence": sentence, "span": {"start": start, "end": end}, "value": str(value), "unit": unit})
            for found_date in _dates(sentence):
                if found_date not in evidence_dates:
                    issues.append({"kind": "unsupported_date", "sentence": sentence, "span": {"start": start, "end": end}, "value": found_date.isoformat()})
            causal = CAUSAL.search(sentence)
            if causal:
                limits = [c for c in sentence_claims if c.get("grade") == 4 and c.get("limits") and c["limits"].casefold() in normalized_sentence and CAUSAL.search(c["claim"])]
                if not limits:
                    issues.append({"kind": "unsupported_causal_language", "sentence": sentence, "span": {"start": start, "end": end}, "phrase": causal.group(0)})
        if driver_analysis and E5_NOTE.casefold() not in text.casefold():
            issues.append({"kind": "missing_causal_boundary_note", "sentence": text, "span": {"start": 0, "end": len(text)}})
        return {"passed": not issues, "issues": issues}
