"""
Best-effort mapping from the app's internal enums to the student-facing
🟢🟡🟠🔴⚪ scheme.

*** THIS MAPPING IS A DRAFT AND HAS NOT BEEN CONFIRMED BY THE PRODUCT OWNER. ***

The product spec names two DIFFERENT 5/4-value schemes that don't line up
1:1:
  - Domain statuses (risk/aggregator.py): VERIFIED, UNVERIFIED, CONTRADICTED,
    SUSPICIOUS, UNABLE_TO_VERIFY (5 values, per-domain).
  - The student-facing display scheme requested in the brief: 🟢 VERIFIED /
    🟡 NEEDS_VERIFICATION / 🟠 SUSPICIOUS / 🔴 HIGH_RISK / ⚪ UNABLE_TO_VERIFY
    (5 values, but "NEEDS_VERIFICATION" and "HIGH_RISK" don't correspond
    to any existing enum name, and it's unclear whether this is meant to
    be an OVERALL case status or a per-domain one).
  - The deterministic risk engine (risk/risk_engine.py) separately produces
    risk_level: LOW / MEDIUM / HIGH / VERY_HIGH (4 values, overall).

Given that ambiguity, this module derives a single OVERALL display status
from a combination of risk_level and domain coverage (falls back to
UNABLE_TO_VERIFY when too little could be verified, regardless of score).
This is one reasonable interpretation, not the only one - confirm the
intended semantics (overall vs. per-domain, and the exact enum mapping)
before the frontend depends on this.
"""

DISPLAY_EMOJI = {
    "VERIFIED": "🟢",
    "NEEDS_VERIFICATION": "🟡",
    "SUSPICIOUS": "🟠",
    "HIGH_RISK": "🔴",
    "UNABLE_TO_VERIFY": "⚪",
}


def derive_display_status(
    risk_level: str, domain_statuses: dict[str, tuple[str, str]]
) -> tuple[str, str]:
    """Returns (display_status, emoji). Draft mapping - see module docstring."""
    statuses = {s for s, _ in domain_statuses.values()}

    # If every domain came back unable to verify (e.g. thin evidence,
    # obscure university), don't claim a risk verdict either way.
    if statuses and statuses.issubset({"UNABLE_TO_VERIFY"}):
        display = "UNABLE_TO_VERIFY"
    elif "CONTRADICTED" in statuses or risk_level == "VERY_HIGH":
        display = "HIGH_RISK"
    elif "SUSPICIOUS" in statuses or risk_level == "HIGH":
        display = "SUSPICIOUS"
    elif risk_level == "MEDIUM":
        display = "NEEDS_VERIFICATION"
    elif risk_level == "LOW" and statuses and statuses.issubset({"VERIFIED", "UNVERIFIED"}):
        display = "VERIFIED"
    else:
        display = "NEEDS_VERIFICATION"

    return display, DISPLAY_EMOJI[display]
