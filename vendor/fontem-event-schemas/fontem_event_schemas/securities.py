"""Shared OpenFIGI security-type taxonomy.

Single source of truth for the company-equity vs pooled-vehicle split
used across the platform: the OpenFIGI loader classifies instruments,
the sinks route fund listings at the InvestmentFund entity, and any
future consumer can join on ``security_type`` without re-deriving the
sets.

Two granularities, because OpenFIGI exposes two fields:

* ``securityType2`` (coarse) — the classifier field. Surveyed against
  prod cohorts (2026-07-04): operating-company equity is Common Stock /
  Preferred Stock / Depositary Receipt / REIT; every pooled vehicle
  (open/closed-end funds, ETPs, fund-of-funds, unit trusts) maps to
  "Mutual Fund".
* ``securityType`` (granular) — the storage field carried on
  UpsertListing. Fund-unit values observed: "Open-End Fund",
  "Closed-End Fund", "ETP", "Fund of Funds"; the rest are defensive
  (documented OpenFIGI values for the same vehicle class).
"""
from __future__ import annotations

# securityType2 (coarse) — classification
COMPANY_SECURITY_TYPES2: frozenset[str] = frozenset({
    "Common Stock", "Preferred Stock", "Depositary Receipt", "REIT",
    "Partnership Shares",
})
FUND_SECURITY_TYPES2: frozenset[str] = frozenset({"Mutual Fund"})

# securityType (granular) — fund-unit values as stored on listings
FUND_SECURITY_TYPES: frozenset[str] = frozenset({
    "Open-End Fund", "Closed-End Fund", "ETP", "Fund of Funds",
    "Mutual Fund", "Unit Trust", "UIT", "SICAV", "FONDS", "Hedge Fund",
})


def is_fund_security_type(security_type: str | None) -> bool:
    """True when a listing's granular ``security_type`` marks it as a
    pooled-vehicle unit (its issuer is an :InvestmentFund, not a
    :Company)."""
    return (security_type or "").strip() in FUND_SECURITY_TYPES
