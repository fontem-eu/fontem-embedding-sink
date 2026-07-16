"""Per-entity `embed_text` composers.

Each function returns (embed_text, entity_id, country, event_date)
for the payload of one `Upsert*` event. Return `None` if the event
should not be embedded (e.g. TaxonomyCodes are labels, not entities;
Relationships are edges; Filings are numeric rows).

Kept small on purpose: the point of `embed_text` is the STRINGS the
model gets, not the whole payload. LaBSE is trained on sentence-scale
inputs — feeding it 100 fields of financial data would just add
noise. Aliases in, names in, one line of context in, done.
"""
from __future__ import annotations
from typing import Optional
Row = tuple[str, str, str, Optional[str], Optional[str]]  # (type, id, text, country, date)


def _clean_join(*parts: object) -> str:
    """Join non-empty stringified parts with ' — ', collapsing whitespace."""
    strs: list[str] = []
    for p in parts:
        if p is None:
            continue
        s = str(p).strip()
        if not s or s.lower() in ("nan", "none", "null", "n/a", "-"):
            continue
        strs.append(" ".join(s.split()))
    return " — ".join(strs)


def company(p: dict) -> Optional[Row]:
    """UpsertCompany → embed name, aliases, context (city + country + legal_form)."""
    name = (p.get("name") or "").strip()
    if not name:
        return None
    aliases = " · ".join(p.get("aliases") or [])
    ctx = _clean_join(p.get("city"), p.get("country"), p.get("legal_form"))
    return (
        "company",
        p["gmr_id"],
        _clean_join(name, aliases, ctx),
        p.get("country"),
        None,
    )


def authority(p: dict) -> Optional[Row]:
    name = (p.get("name") or "").strip()
    if not name:
        return None
    ctx = _clean_join(p.get("city"), p.get("country"), p.get("authority_type"))
    return (
        "authority",
        p["authority_id"],
        _clean_join(name, ctx),
        p.get("country"),
        None,
    )


def contract(p: dict) -> Optional[Row]:
    """UpsertContract — the title is the primary lexical hit;
    procurement contracts are pure "what is this contract about"."""
    title = (p.get("title") or "").strip()
    if not title:
        return None
    return (
        "contract",
        p["ted_notice_id"],
        _clean_join(title, p.get("country")),
        p.get("country"),
        p.get("publication_date"),
    )


def disclosure(p: dict) -> Optional[Row]:
    """UpsertDisclosure — covers eu_cohesion projects and eu_lobbying
    filings. Title carries the semantic weight."""
    title = (p.get("title") or "").strip()
    if not title:
        return None
    system = p.get("system") or "disclosure"
    return (
        system.replace("eu_", "").replace("-", "_"),  # cohesion / lobbying
        p["disclosure_id"],
        _clean_join(title, system),
        None,
        p.get("filed_date"),
    )


def sanctioned_entity(p: dict) -> Optional[Row]:
    name = (p.get("name") or "").strip()
    if not name:
        return None
    aliases = " · ".join(p.get("aliases") or [])
    return (
        "sanction",
        p["entity_id"],
        _clean_join(name, aliases, p.get("subject_type"), p.get("sanction_regime")),
        p.get("nationality"),
        p.get("designation_date"),
    )


def petition(p: dict) -> Optional[Row]:
    title = (p.get("title") or "").strip()
    if not title:
        return None
    ctx = _clean_join(*(p.get("objectives") or [])[:3])
    return (
        "petition",
        p["petition_id"],
        _clean_join(title, ctx),
        None,
        p.get("registration_date"),
    )


def investment_fund(p: dict) -> Optional[Row]:
    name = (p.get("name") or "").strip()
    if not name:
        return None
    return (
        "fund",
        p["gmr_id"],
        _clean_join(name, p.get("country"), p.get("fund_type")),
        p.get("country"),
        None,
    )


# Event-type -> composer. Everything not listed here is skipped.
# (Relationship / TaxonomyCode / Filing / Listing / ExchangeRate /
# AssertSameAs / Begin/EndGraphReplace — not user-facing search
# targets.)
COMPOSERS = {
    "UpsertCompany":         company,
    "UpsertAuthority":       authority,
    "UpsertContract":        contract,
    "UpsertDisclosure":      disclosure,
    "UpsertSanctionedEntity": sanctioned_entity,
    "UpsertPetition":        petition,
    "UpsertInvestmentFund":  investment_fund,
}
