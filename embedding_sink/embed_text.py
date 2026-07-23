"""Per-entity `embed_text` composers.

Each function returns
    (entity_type, entity_id, embed_text, country, event_date, nuts, sector, meta)
for the payload of one `Upsert*` event. Return `None` if the event
should not be embedded (e.g. TaxonomyCodes are labels, not entities;
Relationships are edges; Filings are numeric rows).

Kept small on purpose: the point of `embed_text` is the STRINGS the
model gets, not the whole payload. LaBSE is trained on sentence-scale
inputs — feeding it 100 fields of financial data would just add
noise. Aliases in, names in, one line of context in, done.

Structured filter columns (nuts, sector) and the `meta` jsonb bucket
serve the advanced-search panel — NUTS region prefix, sector top code,
per-type display fields (ticker, value_eur, etc.). None when a field
doesn't naturally exist for the entity kind.
"""
from __future__ import annotations
from typing import Any, Optional

# (type, id, embed_text, country, event_date, nuts, sector, meta)
Row = tuple[
    str, str, str,
    Optional[str], Optional[str],
    Optional[str], Optional[str],
    Optional[dict[str, Any]],
]


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


def _compact_meta(**kv: Any) -> Optional[dict[str, Any]]:
    """Drop None/empty values so we don't store noise in the jsonb column."""
    out = {k: v for k, v in kv.items() if v not in (None, "", [], {})}
    return out or None


def company(p: dict) -> Optional[Row]:
    """UpsertCompany -> embed name, aliases, context (city + country + legal_form)."""
    name = (p.get("name") or "").strip()
    if not name:
        return None
    aliases = " · ".join(p.get("aliases") or [])
    ctx = _clean_join(p.get("city"), p.get("country"), p.get("legal_form"))
    meta = _compact_meta(
        lei=p.get("lei"),
        vat=p.get("vat"),
        legal_form=p.get("legal_form"),
        hq_country=p.get("hq_country"),
        registration_status=p.get("registration_status"),
    )
    return (
        "company",
        p["gmr_id"],
        _clean_join(name, aliases, ctx),
        p.get("country"),
        None,
        # Companies don't ship NUTS today; postal_code + country would
        # need a lookup service. Leave None until that pipeline exists —
        # companies drop out of NUTS-filtered searches (correct: no info
        # = no match).
        None,
        p.get("legal_form"),
        meta,
    )


def authority(p: dict) -> Optional[Row]:
    """UpsertAuthority -> name + (city, country, authority_type) context."""
    name = (p.get("name") or "").strip()
    if not name:
        return None
    ctx = _clean_join(p.get("city"), p.get("country"), p.get("authority_type"))
    meta = _compact_meta(
        national_id=p.get("national_id"),
        url=p.get("url"),
        postal_code=p.get("postal_code"),
        city=p.get("city"),
    )
    return (
        "authority",
        p["authority_id"],
        _clean_join(name, ctx),
        p.get("country"),
        None,
        p.get("nuts"),
        p.get("authority_type"),
        meta,
    )


# value_tier boundaries mirror EU procurement thresholds (simplified,
# sub-Directive, above-Directive, mega).
_TIER_BOUNDS = ((100_000, "S"), (1_000_000, "M"), (10_000_000, "L"))


def _value_tier(value_eur: object) -> Optional[str]:
    """Map a contract's awarded value to an S/M/L/XL bucket. Returns None
    for missing or unparseable values so the facet stays coarse."""
    if value_eur is None:
        return None
    try:
        v = float(value_eur)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    for upper, label in _TIER_BOUNDS:
        if v < upper:
            return label
    return "XL"


def contract(p: dict) -> Optional[Row]:
    """UpsertContract - title is the primary lexical hit; procurement
    contracts are pure "what is this contract about"."""
    title = (p.get("title") or "").strip()
    if not title:
        return None
    cpv = p.get("cpv")
    # CPV top-2 gives the divisional sector (e.g. "45" = construction,
    # "90" = sewage/refuse). Coarse enough for a facet, stable across
    # CPV taxonomy revisions.
    sector = str(cpv)[:2] if cpv else None
    value_eur = p.get("value_eur") or p.get("estimated_value_eur")
    meta = _compact_meta(
        cpv=cpv,
        value_eur=value_eur,
        value_tier=_value_tier(value_eur),
        authority_id=p.get("authority_id"),
        company_gmr_id=p.get("company_gmr_id"),
        language=p.get("language"),
    )
    return (
        "contract",
        p["ted_notice_id"],
        _clean_join(title, p.get("country")),
        p.get("country"),
        p.get("publication_date"),
        p.get("nuts"),
        sector,
        meta,
    )


def disclosure(p: dict) -> Optional[Row]:
    """UpsertDisclosure - covers eu_cohesion projects and eu_lobbying
    filings. Title carries the semantic weight."""
    title = (p.get("title") or "").strip()
    if not title:
        return None
    system = p.get("system") or "disclosure"
    etype = system.replace("eu_", "").replace("-", "_")  # cohesion / lobbying
    # Kohesio + Transparency Register both project NUTS + theme +
    # programme into `details`. Kohesio keys it as `nuts_code`; keep
    # `nuts` as a legacy fallback for older loader fixtures. sector
    # is `theme_code` for cohesion, `interest_area` for lobbying.
    details = p.get("details") if isinstance(p.get("details"), dict) else {}
    nuts = details.get("nuts_code") or details.get("nuts")
    sector = details.get("theme_code") or details.get("interest_area")
    meta = _compact_meta(
        system=system,
        disclosure_type=p.get("disclosure_type"),
        year=p.get("year"),
        details=details or None,
    )
    return (
        etype,
        p["disclosure_id"],
        _clean_join(title, system),
        details.get("country"),
        p.get("filed_date"),
        nuts,
        sector,
        meta,
    )


def sanctioned_entity(p: dict) -> Optional[Row]:
    """UpsertSanctionedEntity -> name, aliases, subject_type, regime."""
    name = (p.get("name") or "").strip()
    if not name:
        return None
    aliases = " · ".join(p.get("aliases") or [])
    meta = _compact_meta(
        eu_reference=p.get("eu_reference"),
        sanction_regime=p.get("sanction_regime"),
        legal_basis=p.get("legal_basis"),
        listing_reason=p.get("listing_reason"),
        subject_type=p.get("subject_type"),
    )
    return (
        "sanction",
        p["entity_id"],
        _clean_join(name, aliases, p.get("subject_type"), p.get("sanction_regime")),
        p.get("nationality"),
        p.get("designation_date"),
        None,
        p.get("sanction_regime"),
        meta,
    )


def petition(p: dict) -> Optional[Row]:
    """UpsertPetition -> title + first three objectives."""
    title = (p.get("title") or "").strip()
    if not title:
        return None
    ctx = _clean_join(*(p.get("objectives") or [])[:3])
    orgs = p.get("organizer_countries") or []
    country = orgs[0] if orgs else None
    meta = _compact_meta(
        status=p.get("status"),
        total_supporters=p.get("total_supporters"),
        answered_date=p.get("answered_date"),
        organizer_countries=orgs or None,
        funding_total_eur=p.get("funding_total_eur"),
    )
    return (
        "petition",
        p["petition_id"],
        _clean_join(title, ctx),
        country,
        p.get("registration_date"),
        None,
        None,
        meta,
    )


def investment_fund(p: dict) -> Optional[Row]:
    """UpsertInvestmentFund -> name + (country, fund_type) context."""
    name = (p.get("name") or "").strip()
    if not name:
        return None
    meta = _compact_meta(
        lei=p.get("lei"),
        legal_form=p.get("legal_form"),
        fund_type=p.get("fund_type"),
    )
    return (
        "fund",
        p["gmr_id"],
        _clean_join(name, p.get("country"), p.get("fund_type")),
        p.get("country"),
        None,
        None,
        p.get("fund_type"),
        meta,
    )


# Event-type -> composer. Everything not listed here is skipped.
# (Relationship / TaxonomyCode / Filing / Listing / ExchangeRate /
# AssertSameAs / Begin/EndGraphReplace - not user-facing search
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
