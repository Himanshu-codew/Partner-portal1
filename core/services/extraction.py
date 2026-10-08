"""Pure text → suggestion extraction (Phase 3).

Everything in this module is a pure function over strings: no database, no
settings, no network, no side effects. It turns OCR text into a small dict
of *suggestions* for a human reviewer to confirm — nothing here is ever
authoritative or auto-applied.

Privacy rules:
  * Aadhaar numbers are NEVER extracted or stored. Any 12-digit run
    (contiguous or grouped 4-4-4) is masked to ``XXXX XXXX 1234`` (last four
    kept) before it can reach the database, and again here as defence in
    depth for callers that skip the masking step.
  * Because the mask runs first, a 12-digit run can never be suggested as a
    bank account number either.
"""

import re

# Standard 10-character PAN: 5 letters + 4 digits + 1 letter.
PAN_RE = re.compile(r'\b[A-Z]{5}[0-9]{4}[A-Z]\b')

# Standard 15-character GSTIN.
GSTIN_RE = re.compile(r'\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b')

# Standard 11-character IFSC: 4 letters + '0' + 6 alphanumerics.
IFSC_RE = re.compile(r'\b[A-Z]{4}0[A-Z0-9]{6}\b')

# Bank account candidates: 9–18 digits (used only for BANK documents).
ACCOUNT_RE = re.compile(r'(?<!\d)\d{9,18}(?!\d)')

# Aadhaar shapes: contiguous 12 digits or grouped 4-4-4.
AADHAAR_RE = re.compile(r'(?<!\d)\d{12}(?!\d)')
AADHAAR_GROUPED_RE = re.compile(r'(?<!\d)\d{4}[-\s]\d{4}[-\s]\d{4}(?!\d)')

# Invoice / bill number: label + a candidate containing at least one digit.
INVOICE_NO_RE = re.compile(
    r'\b(?:invoice|inv|bill)\s*(?:no\.?|number|#)?\s*[:#\-]?\s*'
    r'([A-Za-z0-9][A-Za-z0-9\-/]*)',
    re.IGNORECASE,
)

# Money after a total-ish label ("grand total", "total", "amount payable"…).
TOTAL_RE = re.compile(
    r'\b(?:grand\s+total|total\s+amount|amount\s+payable|net\s+payable|'
    r'balance\s+due|total)\b'
    r'\s*(?:due|payable)?\s*(?:[:#@-]|@)?\s*'
    r'(?:rs\.?|inr|₹|\$|usd)?\s*'
    r'([\d][\d,]*(?:\.\d{1,2})?)',
    re.IGNORECASE,
)

EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z]{2,})+')

# 10-digit Indian mobile (6–9 leading digit).
MOBILE_RE = re.compile(r'(?<!\d)[6-9]\d{9}(?!\d)')


def mask_aadhaar(text):
    """Replace every 12-digit Aadhaar-shaped run with ``XXXX XXXX 1234``.

    Handles both ``1234 5678 9012`` and ``123456789012``. Returns '' for
    empty input; never raises.
    """
    if not text:
        return ''

    def _mask(match):
        digits = re.sub(r'\D', '', match.group(0))
        if len(digits) != 12:
            return match.group(0)
        return 'XXXX XXXX ' + digits[-4:]

    masked = AADHAAR_GROUPED_RE.sub(_mask, text)
    return AADHAAR_RE.sub(_mask, masked)


def _uniq(values):
    seen = set()
    ordered = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def extract_suggestions(text, doc_type='OTHER'):
    """Build the suggestion dict shown (read-only) to the reviewer.

    Always returns the same keys; values are strings or lists of strings
    (empty when nothing was found). Aadhaar runs are masked before any
    pattern runs, so an Aadhaar number can never surface here.
    """
    text = mask_aadhaar(text or '')

    pan = PAN_RE.search(text)
    gst = GSTIN_RE.search(text)
    ifsc = IFSC_RE.search(text)

    accounts = []
    if doc_type == 'BANK':
        # Only bank documents offer account numbers, and the mask above has
        # already removed any 12-digit run that could be an Aadhaar number.
        accounts = _uniq(ACCOUNT_RE.findall(text))

    invoice_numbers = []
    for candidate in INVOICE_NO_RE.findall(text):
        if len(candidate) >= 3 and any(ch.isdigit() for ch in candidate):
            invoice_numbers.append(candidate)
    invoice_numbers = _uniq(invoice_numbers)

    amounts = _uniq(TOTAL_RE.findall(text))

    suggestions = {
        'pan': pan.group(0) if pan else '',
        'gst': gst.group(0) if gst else '',
        'ifsc': ifsc.group(0) if ifsc else '',
        'account_numbers': accounts,
        'invoice_numbers': invoice_numbers,
        'amount': amounts[0] if amounts else '',
        'emails': _uniq(EMAIL_RE.findall(text)),
        'mobiles': _uniq(MOBILE_RE.findall(text)),
    }
    return suggestions
