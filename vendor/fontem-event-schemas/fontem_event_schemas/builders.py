"""Typed builders for common event payloads.

Producers should prefer these over hand-rolling dicts: they keep
the field set in lockstep with the schema and let mypy / IDE flag
typos at edit time. Each returns a dict conforming to the
corresponding JSON Schema.
"""
from __future__ import annotations

from typing import Any, Mapping


def upsert_sanctioned_entity(
    *,
    entity_id: str,
    eu_reference: str,
    name: str | None = None,
    aliases: list[str] | None = None,
    nationality: str | None = None,
    designation_date: str | None = None,
    sanction_regime: str | None = None,
    legal_basis: str | None = None,
    listing_reason: str | None = None,
    subject_type: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertSanctionedEntity payload (v1)."""
    out: dict[str, Any] = {
        "entity_id":    entity_id,
        "eu_reference": eu_reference,
    }
    for k, v in (
        ("name", name), ("aliases", aliases),
        ("nationality", nationality),
        ("designation_date", designation_date),
        ("sanction_regime", sanction_regime),
        ("legal_basis", legal_basis),
        ("listing_reason", listing_reason),
        ("subject_type", subject_type),
    ):
        if v is not None and v != "":
            out[k] = v
    return out


def upsert_filing(
    *,
    gmr_id: str,
    year: int,
    source: str,
    filing_date: str | None = None,
    **financials: float | None,
) -> dict[str, Any]:
    """Build an UpsertFiling payload (v1).

    ``financials`` accepts any of the optional numeric Filing
    fields (revenue, net_income, …); None/missing values are
    dropped so the JSON stays compact and schema-clean.
    """
    out: dict[str, Any] = {
        "gmr_id": gmr_id, "year": year, "source": source,
    }
    if filing_date:
        out["filing_date"] = filing_date
    for k, v in financials.items():
        if v is not None:
            out[k] = float(v)
    return out


# GLEIF identity block (LEI-CDF v3.1) — carried on `identity`. Stored
# verbatim from the source, never inferred; a source that says nothing
# about a field simply omits it. `aliases` is a list; every other key is
# a scalar mapped straight onto the schema.
COMPANY_IDENTITY_FIELDS = (
    "entity_kind", "registered_as", "registered_at", "jurisdiction",
    "registration_status", "entity_creation_date", "address", "city",
    "region", "hq_address", "hq_city", "hq_region", "hq_country",
    "hq_postal_code", "aliases",
)


def upsert_company(
    *,
    gmr_id: str,
    name: str | None = None,
    country: str | None = None,
    lei: str | None = None,
    vat: str | None = None,
    cik: str | None = None,
    active: bool | None = None,
    legal_form: str | None = None,
    postal_code: str | None = None,
    identity: "Mapping[str, Any] | None" = None,
) -> dict[str, Any]:
    """Build an UpsertCompany payload (v1).

    `identity` bundles the optional GLEIF identity block — see
    ``COMPANY_IDENTITY_FIELDS``. Keys map straight onto the schema;
    None/"" values drop out and `aliases` is emitted only when non-empty.
    Unknown keys are forwarded and fail schema validation loudly rather
    than being silently swallowed."""
    out: dict[str, Any] = {"gmr_id": gmr_id}
    for k, v in (
        ("name", name), ("country", country), ("lei", lei),
        ("vat", vat), ("cik", cik), ("active", active),
        ("legal_form", legal_form), ("postal_code", postal_code),
    ):
        if v is not None and v != "":
            out[k] = v
    for k, v in (identity or {}).items():
        if k == "aliases":
            if v:
                out["aliases"] = list(v)
        elif v is not None and v != "":
            out[k] = v
    return out


def upsert_investment_fund(
    *,
    gmr_id: str,
    name: str | None = None,
    country: str | None = None,
    lei: str | None = None,
    active: bool | None = None,
    legal_form: str | None = None,
    fund_type: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertInvestmentFund payload (v1). Same gmr_id
    derivation as companies so an entity that first landed as a
    Company keeps its identity; sinks relabel the node."""
    out: dict[str, Any] = {"gmr_id": gmr_id}
    for k, v in (
        ("name", name), ("country", country), ("lei", lei),
        ("active", active), ("legal_form", legal_form),
        ("fund_type", fund_type),
    ):
        if v is not None and v != "":
            out[k] = v
    return out


def upsert_listing(
    *,
    ticker: str,
    company_gmr_id: str,
    exchange: str | None = None,
    currency: str | None = None,
    active: bool | None = None,
    isin: str | None = None,
    mic: str | None = None,
    security_type: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertListing payload (v1)."""
    out: dict[str, Any] = {
        "ticker": ticker, "company_gmr_id": company_gmr_id,
    }
    for k, v in (
        ("exchange", exchange), ("currency", currency),
        ("active", active), ("isin", isin), ("mic", mic),
        ("security_type", security_type),
    ):
        if v is not None and v != "":
            out[k] = v
    return out


def upsert_authority(
    *,
    authority_id: str,
    name: str | None = None,
    country: str | None = None,
    authority_type: str | None = None,
    national_id: str | None = None,
    url: str | None = None,
    postal_code: str | None = None,
    city: str | None = None,
    nuts: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertAuthority payload (v1)."""
    out: dict[str, Any] = {"authority_id": authority_id}
    for k, v in (
        ("name", name), ("country", country),
        ("authority_type", authority_type),
        ("national_id", national_id), ("url", url),
        ("postal_code", postal_code), ("city", city), ("nuts", nuts),
    ):
        if v is not None and v != "":
            out[k] = v
    return out


def upsert_contract(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    *,
    ted_notice_id: str,
    ted_publication_number: str | None = None,
    title: str | None = None,
    authority_id: str | None = None,
    company_gmr_id: str | None = None,
    publication_date: str | None = None,
    value_eur: float | None = None,
    value_currency: str | None = None,
    value_original: float | None = None,
    value_before_eur: float | None = None,
    value_before_original: float | None = None,
    estimated_value_eur: float | None = None,
    value_payable_eur: float | None = None,
    value_confidence: float | None = None,
    value_confidence_consistency: float | None = None,
    value_confidence_plausibility: float | None = None,
    value_quality_flag: str | None = None,
    value_low_confidence: bool | None = None,
    value_payable_discrepancy: bool | None = None,
    value_quarantined: bool | None = None,
    value_quarantine_reason: str | None = None,
    match_tier: str | None = None,
    match_confidence: float | None = None,
    match_layer: int | None = None,
    cpv: str | None = None,
    nuts: str | None = None,
    language: str | None = None,
    country: str | None = None,
    procedure_type: str | None = None,
    tenders_received: int | None = None,
    award_criterion_type: str | None = None,
    submission_deadline: str | None = None,
    is_framework: bool | None = None,
    eu_funded: bool | None = None,
    funding_programme: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertContract payload (v1).

    ``ted_notice_id`` is the eForms internal UUID (the cbc:ID root
    identifier). ``ted_publication_number`` is the human-readable
    ``<seq>-<year>`` identifier TED assigns at publish time and which
    TED's public detail URL is keyed by — capturing it at ETL time
    lets readers skip the runtime UUID→pub-num search call.

    ``country`` is the alpha-3 country of the contracting authority (the
    acquirer). Cascaded onto the Contract at write time so jurisdictional
    panels can group contracts without traversing to Authority.

    Value-quality fields (all derived by ``contract_confidence``):
    ``value_eur`` is the awarded value the loader chose to trust (the
    eForms ``TotalAmount``, falling back to ``PayableAmount``).
    ``estimated_value_eur`` and ``value_payable_eur`` are the two
    cross-check signals kept alongside it. ``value_confidence`` in
    ``[0, 1]`` is consistency × plausibility; ``value_low_confidence`` is
    the boolean gate consumers use to exclude a contract from default
    aggregates. ``value_quality_flag`` explains why (ok /
    value_disagreement / implausible_magnitude / concession_negative /
    zero_value / no_awarded_value / unverified_single_signal).
    ``value_payable_discrepancy`` marks a notice whose payable disagrees
    with the stored total (an internal source inconsistency) even when the
    contract is otherwise kept.
    """
    out: dict[str, Any] = {"ted_notice_id": ted_notice_id}
    for k, v in (
        ("ted_publication_number", ted_publication_number),
        ("title", title), ("authority_id", authority_id),
        ("company_gmr_id", company_gmr_id),
        ("publication_date", publication_date),
        ("value_eur", value_eur), ("value_currency", value_currency),
        ("value_original", value_original),
        ("value_before_eur", value_before_eur),
        ("value_before_original", value_before_original),
        ("estimated_value_eur", estimated_value_eur),
        ("value_payable_eur", value_payable_eur),
        ("value_confidence", value_confidence),
        ("value_confidence_consistency", value_confidence_consistency),
        ("value_confidence_plausibility", value_confidence_plausibility),
        ("value_quality_flag", value_quality_flag),
        ("value_low_confidence", value_low_confidence),
        ("value_payable_discrepancy", value_payable_discrepancy),
        ("value_quarantined", value_quarantined),
        ("value_quarantine_reason", value_quarantine_reason),
        ("match_tier", match_tier),
        ("match_confidence", match_confidence),
        ("match_layer", match_layer),
        ("cpv", cpv), ("nuts", nuts), ("language", language),
        ("country", country),
        ("procedure_type", procedure_type),
        ("tenders_received", tenders_received),
        ("award_criterion_type", award_criterion_type),
        ("submission_deadline", submission_deadline),
        ("is_framework", is_framework),
        ("eu_funded", eu_funded),
        ("funding_programme", funding_programme),
    ):
        if v is not None and v != "":
            out[k] = v
    return out


def upsert_taxonomy_code(
    *,
    system: str,
    code: str,
    label: str | None = None,
    label_lang: str | None = None,
    parent_code: str | None = None,
    level: int | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertTaxonomyCode payload (v1)."""
    out: dict[str, Any] = {"system": system, "code": code}
    for k, v in (
        ("label", label), ("label_lang", label_lang),
        ("parent_code", parent_code),
        ("level", level), ("description", description),
    ):
        if v is not None and v != "":
            out[k] = v
    return out


def upsert_relationship(
    *,
    src_iri: str,
    dst_iri: str,
    predicate: str,
    properties: dict[str, Any] | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertRelationship payload (v1)."""
    out: dict[str, Any] = {
        "src_iri": src_iri, "dst_iri": dst_iri, "predicate": predicate,
    }
    if properties:
        out["properties"] = properties
    if valid_from:
        out["valid_from"] = valid_from
    if valid_to:
        out["valid_to"] = valid_to
    return out


def upsert_disclosure(
    *,
    system: str,
    disclosure_id: str,
    company_gmr_id: str | None = None,
    disclosure_type: str | None = None,
    filed_date: str | None = None,
    year: int | None = None,
    title: str | None = None,
    url: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an UpsertDisclosure payload (v1).

    ``company_gmr_id`` is optional — some regimes (EU lobbying)
    file under non-Company registrants, in which case the
    registrant identity rides in ``details``.
    """
    out: dict[str, Any] = {
        "system": system,
        "disclosure_id": disclosure_id,
    }
    if company_gmr_id:
        out["company_gmr_id"] = company_gmr_id
    for k, v in (
        ("disclosure_type", disclosure_type),
        ("filed_date", filed_date), ("year", year),
        ("title", title), ("url", url),
    ):
        if v is not None and v != "":
            out[k] = v
    if details:
        out["details"] = details
    return out


def upsert_exchange_rate(
    *,
    base: str,
    target: str,
    date: str,
    rate: float,
    source: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertExchangeRate payload (v1)."""
    out: dict[str, Any] = {
        "base": base, "target": target,
        "date": date, "rate": float(rate),
    }
    if source:
        out["source"] = source
    return out


def assert_same_as(
    *,
    a_iri: str,
    b_iri: str,
    confidence: float,
    method: str,
    tier: str | None = None,
    matched_via_alias: bool = False,
    rule: str | None = None,
) -> dict[str, Any]:
    """Build an AssertSameAs payload (v1)."""
    out: dict[str, Any] = {
        "a_iri": a_iri, "b_iri": b_iri,
        "confidence": float(confidence), "method": method,
        "matched_via_alias": bool(matched_via_alias),
    }
    if tier is not None:
        out["tier"] = tier
    if rule is not None:
        out["rule"] = rule
    return out


def begin_graph_replace(
    *, graph_iri: str, label: str, domain: str | None = None,
) -> dict[str, Any]:
    """Build a BeginGraphReplace control payload (v1)."""
    out: dict[str, Any] = {"graph_iri": graph_iri, "label": label}
    if domain:
        out["domain"] = domain
    return out


def end_graph_replace(
    *, graph_iri: str, domain: str | None = None,
) -> dict[str, Any]:
    """Build an EndGraphReplace control payload (v1)."""
    out: dict[str, Any] = {"graph_iri": graph_iri}
    if domain:
        out["domain"] = domain
    return out


def upsert_petition(  # pylint: disable=too-many-arguments,too-many-locals
    *,
    system: str,
    petition_id: str,
    title: str | None = None,
    status: str | None = None,
    objectives: str | None = None,
    registration_date: str | None = None,
    collection_start_date: str | None = None,
    collection_deadline: str | None = None,
    closed_date: str | None = None,
    submitted_date: str | None = None,
    answered_date: str | None = None,
    total_supporters: int | None = None,
    support_link: str | None = None,
    organizer_names: list[str] | None = None,
    organizer_roles: list[str] | None = None,
    organizer_countries: list[str] | None = None,
    funding_total_eur: float | None = None,
    funding_sponsor_count: int | None = None,
    registration_decision_celex: str | None = None,
    answer_refs: list[str] | None = None,
    latest_update: str | None = None,
) -> dict[str, Any]:
    """Build an UpsertPetition payload (v1)."""
    out: dict[str, Any] = {
        "system": system,
        "petition_id": petition_id,
    }
    for k, v in (
        ("title", title), ("status", status), ("objectives", objectives),
        ("registration_date", registration_date),
        ("collection_start_date", collection_start_date),
        ("collection_deadline", collection_deadline),
        ("closed_date", closed_date), ("submitted_date", submitted_date),
        ("answered_date", answered_date),
        ("total_supporters", total_supporters),
        ("support_link", support_link),
        ("organizer_names", organizer_names),
        ("organizer_roles", organizer_roles),
        ("organizer_countries", organizer_countries),
        ("funding_total_eur", funding_total_eur),
        ("funding_sponsor_count", funding_sponsor_count),
        ("registration_decision_celex", registration_decision_celex),
        ("answer_refs", answer_refs), ("latest_update", latest_update),
    ):
        if v is not None:
            out[k] = v
    return out
