"""Procurement-integrity indicators derived from a Contract's own fields.

One implementation, shared by the Neo4j sink, the Virtuoso sink, and the
API, so the red flags are materialised identically in every store (and
stay hot-queryable) instead of being recomputed ad-hoc per consumer.

Grounded in the EC Single Market Scoreboard headline indicators + the
DIGIWHIST / opentender.eu Corruption Risk Index (CRI) red-flag family
(ECA SR 28/2023 methodology). Every flag is per-contract and computed
only from fields the contract already carries; a flag is omitted when
its input is absent (None) so "unknown" never reads as "not flagged".
"""
from __future__ import annotations

from typing import Any

# Procedures that ran with no (or curtailed) prior competition.
_NON_OPEN = {"restricted", "neg-w-call", "neg-wo-call", "oth-single", "oth-mult"}
# Procedures with no public call for bids at all (direct-ish awards).
_NO_CALL = {"neg-wo-call", "oth-single"}


def contract_red_flags(p: dict[str, Any]) -> dict[str, Any]:
    """Return the integrity flags derivable from contract payload ``p``.

    Keys (all optional — present only when the input field is):
      is_single_bidder   tenders_received == 1   (SMSB headline)
      is_non_open        procedure not 'open'
      is_no_call         procedure had no call for bids (direct-ish)
      is_price_only      award on lowest price only (no quality criterion)
      integrity_red_flags  count of the above that fired (CRI-lite)
    """
    out: dict[str, Any] = {}
    tenders = p.get("tenders_received")
    if tenders is not None:
        out["is_single_bidder"] = tenders == 1
    procedure = p.get("procedure_type")
    if procedure is not None:
        out["is_non_open"] = procedure in _NON_OPEN
        out["is_no_call"] = procedure in _NO_CALL
    criterion = p.get("award_criterion_type")
    if criterion is not None:
        out["is_price_only"] = criterion == "price"
    bool_flags = [v for v in out.values() if isinstance(v, bool)]
    if bool_flags:
        out["integrity_red_flags"] = sum(1 for v in bool_flags if v)
    return out
