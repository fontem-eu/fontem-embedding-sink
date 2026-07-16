"""Builder coverage for the value-quality fields on upsert_contract.

The schema/example tests validate shapes; this exercises the builder
itself — that it threads the new value-quality fields through, drops
None/empty, and that its output validates against the schema (including
the bool fields, which must survive even when False).
"""
from fontem_event_schemas import builders, validate


def test_upsert_contract_threads_value_quality_fields():
    """All value-quality fields land on the payload and it validates."""
    p = builders.upsert_contract(
        ted_notice_id="35ecc2b8",
        title="AQUISICAO DE AERONAVES",
        value_eur=7_274_615.93,
        value_currency="EUR",
        value_original=7_274_615.93,
        estimated_value_eur=7_317_073.17,
        value_payable_eur=7_274_615_930.0,
        value_confidence=0.71,
        value_confidence_consistency=0.71,
        value_confidence_plausibility=1.0,
        value_quality_flag="ok",
        value_low_confidence=False,
        value_payable_discrepancy=True,
        cpv="35611500",
        country="PRT",
    )
    assert p["estimated_value_eur"] == 7_317_073.17
    assert p["value_payable_eur"] == 7_274_615_930.0
    assert p["value_confidence"] == 0.71
    assert p["value_quality_flag"] == "ok"
    # False bool must be preserved (it is meaningful: kept and counted).
    assert p["value_low_confidence"] is False
    assert p["value_payable_discrepancy"] is True
    validate("UpsertContract", 1, p)  # raises on failure


def test_upsert_contract_flagged_value_validates():
    """A flagged (low-confidence) contract payload validates."""
    p = builders.upsert_contract(
        ted_notice_id="greek-drama",
        value_eur=1_073_062_200_000.0,
        estimated_value_eur=1_083_901.24,
        value_confidence=0.0,
        value_quality_flag="implausible_magnitude",
        value_low_confidence=True,
    )
    assert p["value_low_confidence"] is True
    assert p["value_quality_flag"] == "implausible_magnitude"
    validate("UpsertContract", 1, p)


def test_upsert_contract_omits_unset_value_quality_fields():
    """Unset value-quality fields are omitted from the payload."""
    p = builders.upsert_contract(ted_notice_id="minimal")
    for k in (
        "estimated_value_eur", "value_payable_eur", "value_confidence",
        "value_quality_flag", "value_low_confidence",
        "value_payable_discrepancy",
    ):
        assert k not in p
    validate("UpsertContract", 1, p)


def test_upsert_contract_threads_integrity_fields():
    """Tender-integrity fields land on the payload and it validates."""
    p = builders.upsert_contract(
        ted_notice_id="integrity-1",
        procedure_type="open",
        tenders_received=1,
        award_criterion_type="price",
        submission_deadline="2026-03-01",
        is_framework=False,
        eu_funded=True,
        funding_programme="RRF",
    )
    assert p["procedure_type"] == "open"
    assert p["tenders_received"] == 1            # single-bidder signal
    assert p["award_criterion_type"] == "price"
    assert p["submission_deadline"] == "2026-03-01"
    assert p["is_framework"] is False            # meaningful False preserved
    assert p["eu_funded"] is True
    assert p["funding_programme"] == "RRF"
    validate("UpsertContract", 1, p)             # raises on failure


def test_upsert_contract_threads_modification_before_values():
    """The pre-modification before-values thread through and validate —
    the corruption-signal delta pairs value_before_* with value_*
    (here the €1,092 -> €2,184 doubling from a real legacy F20)."""
    p = builders.upsert_contract(
        ted_notice_id="24082-2024",
        value_eur=2184.6,
        value_currency="EUR",
        value_original=2184.6,
        value_before_eur=1092.3,
        value_before_original=1092.3,
    )
    assert p["value_before_eur"] == 1092.3
    assert p["value_before_original"] == 1092.3
    validate("UpsertContract", 1, p)


def test_upsert_contract_omits_unset_before_values():
    """Non-modification contracts carry no before-values."""
    p = builders.upsert_contract(ted_notice_id="minimal")
    assert "value_before_eur" not in p
    assert "value_before_original" not in p


def test_upsert_investment_fund_validates_and_omits_unset():
    from fontem_event_schemas import validate
    from fontem_event_schemas.builders import upsert_investment_fund
    payload = upsert_investment_fund(
        gmr_id="0b6cbfa6-6a30-5efc-9b4f-3e56d0f3f5a2",
        name="EXAMPLE UCITS FUND",
        lei="2138008K5B3Z4E8DHN12",
        fund_type="Open-End Fund",
    )
    assert "country" not in payload      # unset fields stay absent
    assert payload["fund_type"] == "Open-End Fund"
    validate("UpsertInvestmentFund", 1, payload)   # raises on failure


def test_upsert_listing_threads_security_type():
    from fontem_event_schemas import validate
    from fontem_event_schemas.builders import upsert_listing
    payload = upsert_listing(
        ticker="EGL", company_gmr_id="0b6cbfa6-6a30-5efc-9b4f-3e56d0f3f5a2",
        exchange="PL", security_type="Common Stock",
    )
    assert payload["security_type"] == "Common Stock"
    validate("UpsertListing", 1, payload)


def test_upsert_listing_omits_unset_security_type():
    from fontem_event_schemas.builders import upsert_listing
    payload = upsert_listing(
        ticker="EGL", company_gmr_id="0b6cbfa6-6a30-5efc-9b4f-3e56d0f3f5a2",
    )
    assert "security_type" not in payload


def test_fund_security_type_taxonomy():
    from fontem_event_schemas.securities import (
        COMPANY_SECURITY_TYPES2,
        FUND_SECURITY_TYPES2,
        is_fund_security_type,
    )
    assert "Common Stock" in COMPANY_SECURITY_TYPES2
    assert "Mutual Fund" in FUND_SECURITY_TYPES2
    assert not COMPANY_SECURITY_TYPES2 & FUND_SECURITY_TYPES2
    assert is_fund_security_type("Open-End Fund")
    assert is_fund_security_type("ETP")
    assert not is_fund_security_type("Common Stock")
    assert not is_fund_security_type(None)


def test_upsert_contract_threads_quarantine_fields():
    from fontem_event_schemas import validate
    from fontem_event_schemas.builders import upsert_contract
    payload = upsert_contract(
        ted_notice_id="n-1",
        value_quarantined=True,
        value_quarantine_reason="implausible_magnitude",
    )
    assert payload["value_quarantined"] is True
    assert payload["value_quarantine_reason"] == "implausible_magnitude"
    validate("UpsertContract", 1, payload)
    # unset stays absent — a normal contract carries neither key
    clean = upsert_contract(ted_notice_id="n-2")
    assert "value_quarantined" not in clean


def test_upsert_company_threads_gleif_identity_block():
    """Real GLEIF values (Carlsberg A/S, LEI 5299001O0WJQYB5GYZ19) —
    the identity block is stored verbatim; unset fields stay absent."""
    from fontem_event_schemas import validate
    from fontem_event_schemas.builders import upsert_company
    p = upsert_company(
        gmr_id="00000000-0000-5000-8000-000000000001",
        name="CARLSBERG A/S", country="DNK",
        lei="5299001O0WJQYB5GYZ19", postal_code="1799",
        identity={
            "entity_kind": "GENERAL",
            "registered_as": "61056416", "registered_at": "RA000170",
            "jurisdiction": "DK", "registration_status": "ISSUED",
            "entity_creation_date": "1999-10-16",
            "address": "J.C. Jacobsens Gade 1", "city": "København V",
            "region": "DK-84",
            "aliases": ["Carlsberg Group"],
        },
    )
    assert p["entity_kind"] == "GENERAL"
    assert p["registered_as"] == "61056416"
    assert p["registered_at"] == "RA000170"
    assert p["aliases"] == ["Carlsberg Group"]
    validate("UpsertCompany", 1, p)
    # an EDGAR/other-source company that says nothing about kind carries
    # NO entity_kind key — silence, not a guess.
    silent = upsert_company(gmr_id="00000000-0000-5000-8000-000000000002",
                            name="Some LLC", cik="0000320193")
    assert "entity_kind" not in silent
    assert "aliases" not in silent
    validate("UpsertCompany", 1, silent)


def test_upsert_contract_threads_match_provenance():
    from fontem_event_schemas import validate
    from fontem_event_schemas.builders import upsert_contract
    exact = upsert_contract(ted_notice_id="n-1", company_gmr_id="g1",
                            match_tier="lei", match_confidence=1.0,
                            match_layer=2)
    assert exact["match_tier"] == "lei"
    assert exact["match_confidence"] == 1.0
    validate("UpsertContract", 1, exact)
    # a contract with no resolved company carries no provenance
    bare = upsert_contract(ted_notice_id="n-2")
    assert "match_tier" not in bare
    validate("UpsertContract", 1, bare)


def test_upsert_sanctioned_entity_threads_subject_type():
    from fontem_event_schemas.builders import upsert_sanctioned_entity
    from fontem_event_schemas.validate import validate as _validate

    person = upsert_sanctioned_entity(
        entity_id="p-1", eu_reference="EU.1.1", name="Jane Doe",
        subject_type="person", nationality="RUS",
    )
    assert person["subject_type"] == "person"
    _validate("UpsertSanctionedEntity", 1, person)

    entity = upsert_sanctioned_entity(
        entity_id="e-1", eu_reference="EU.2.2", name="ACME OAO",
        subject_type="entity",
    )
    _validate("UpsertSanctionedEntity", 1, entity)

    # pre-2026-07-14 producers say nothing about subject type — silence,
    # not a guess, and still valid.
    silent = upsert_sanctioned_entity(entity_id="s-1", eu_reference="EU.3.3")
    assert "subject_type" not in silent
    _validate("UpsertSanctionedEntity", 1, silent)

def test_upsert_petition_validates_and_omits_unset():
    from fontem_event_schemas.builders import upsert_petition
    from fontem_event_schemas.validate import validate as _validate

    full = upsert_petition(
        system="eu-eci", petition_id="ECI(2024)000007",
        title="Stop Destroying Videogames", status="ANSWERED",
        registration_date="2024-06-19", total_supporters=1294188,
        organizer_names=["Daniel ONDRUSKA"], organizer_roles=["REPRESENTATIVE"],
        registration_decision_celex="32024D1824", answer_refs=["C(2026)4110"],
    )
    assert full["total_supporters"] == 1294188
    _validate("UpsertPetition", 1, full)

    bare = upsert_petition(system="eu-eci", petition_id="ECI(2026)000001")
    assert "title" not in bare
    _validate("UpsertPetition", 1, bare)
