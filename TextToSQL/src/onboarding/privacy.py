"""Fail-closed detection and redaction helpers for warehouse sample values."""
from __future__ import annotations

import html
import ipaddress
import json
import re
from urllib.parse import quote, unquote

SENSITIVE_COLUMN = re.compile(
    r"(^|_)(email|e_mail|phone|mobile|ssn|social_security|password|passwd|token|secret|address|birth|dob|credit_card|card_number|full_name|first_name|last_name|customer_name|username|ip_address|passport|tax_id|bank_account)(_|$)",
    re.I,
)
EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]{1,128}@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])", re.I)
SSN = re.compile(r"(?<!\d)(?:\d{3}-\d{2}-\d{4}|\d{9})(?!\d)")
AID = re.compile(r"(?<!\d)(?:\d{4}[ -]?){2}\d{4}(?!\d)")
PHONE = re.compile(r"(?<!\w)\+?\d(?:[\s().-]*\d){6,14}(?!\w)")
PLAIN_PHONE = re.compile(r"(?<!\d)\d{10,15}(?!\d)")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")
API_KEY = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})\b")
HASH = re.compile(r"(?<![A-Fa-f0-9])[A-Fa-f0-9]{32}(?:[A-Fa-f0-9]{8}|[A-Fa-f0-9]{32})?(?![A-Fa-f0-9])")
TOKEN_CANDIDATE = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
MASK = "[REDACTED]"


def has_luhn_checksum(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    parity = len(digits) % 2
    for index, char in enumerate(digits):
        digit = int(char)
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _normalized_forms(value: str) -> set[str]:
    forms = {value}
    pending = [value]
    while pending and len(forms) < 32:
        current = pending.pop()
        decoded = html.unescape(unquote(current))
        if decoded not in forms:
            forms.add(decoded)
            pending.append(decoded)
        try:
            parsed = json.loads(current)
        except (json.JSONDecodeError, TypeError):
            continue
        values = parsed.values() if isinstance(parsed, dict) else parsed if isinstance(parsed, list) else [parsed]
        for item in values:
            if isinstance(item, str) and item not in forms:
                forms.add(item)
                pending.append(item)
    return forms


def sensitive_value(value) -> bool:
    if value is None:
        return False
    text = str(value)
    for form in _normalized_forms(text):
        phone_is_date = bool(re.search(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}[/-]\d{2}[/-]\d{4})\b", form))
        if EMAIL.search(form) or SSN.search(form) or AID.search(form) or (PHONE.search(form) and not phone_is_date) or JWT.search(form) or API_KEY.search(form) or HASH.search(form):
            return True
        if not phone_is_date and PLAIN_PHONE.search(form):
            return True
        for candidate in re.findall(r"(?:\d[ -]?){13,19}", form):
            if has_luhn_checksum(candidate):
                return True
        for candidate in TOKEN_CANDIDATE.findall(form):
            if JWT.fullmatch(candidate):
                return True
        # Parse IPv4/IPv6-like tokens without treating arbitrary words as addresses.
        for candidate in re.findall(r"(?<![\w])(?:\d{1,3}\.){3}\d{1,3}(?![\w])", form):
            try:
                ipaddress.ip_address(candidate)
                return True
            except ValueError:
                pass
        if ":" in form and re.search(r"[A-Fa-f0-9]{1,4}:[A-Fa-f0-9:]{2,}", form):
            try:
                ipaddress.ip_address(form.strip(" []"))
                return True
            except ValueError:
                pass
    return False


def sensitive_variants(value) -> set[str]:
    """Return short-lived redaction needles; callers must not persist this set."""
    if value is None:
        return set()
    text = str(value)
    variants = set()
    for form in _normalized_forms(text):
        if len(form) >= 4:
            variants.add(form)
        if "@" in form:
            local = form.split("@", 1)[0]
            if len(local) >= 4:
                variants.add(local)
        digits = re.sub(r"\D", "", form)
        if len(digits) >= 4:
            variants.add(digits[-4:])
    return variants


def redact_text(text: str, needles) -> str:
    return make_redactor(needles)(text)


def make_redactor(needles):
    values = {str(v) for v in needles if v is not None and len(str(v)) >= 4}
    values.update(quote(value, safe="") for value in tuple(values))
    if not values:
        return lambda text: str(text)
    pattern = re.compile("|".join(re.escape(value) for value in sorted(values, key=len, reverse=True)), re.I)
    return lambda text: pattern.sub(MASK, str(text))


def should_mask_column(name: str, sample_values) -> bool:
    return bool(SENSITIVE_COLUMN.search(name)) or any(sensitive_value(value) for value in sample_values)


def redact_payload(payload):
    """Pattern-scrub a nested payload before it is persisted or sent to logs."""
    strings = []

    def collect(value):
        if isinstance(value, dict):
            for child in value.values():
                collect(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                collect(child)
        elif isinstance(value, str) and sensitive_value(value):
            strings.append(value)

    collect(payload)
    needles = set().union(*(sensitive_variants(value) for value in strings)) if strings else set()
    redact_string = make_redactor(needles)

    def redact(value):
        if isinstance(value, dict):
            return {key: redact(child) for key, child in value.items()}
        if isinstance(value, list):
            return [redact(child) for child in value]
        if isinstance(value, tuple):
            return [redact(child) for child in value]
        if isinstance(value, str):
            return MASK if sensitive_value(value) else redact_string(value)
        return value

    return redact(payload)
