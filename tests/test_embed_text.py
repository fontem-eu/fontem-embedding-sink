"""Unit tests for the embed_text composers.

Composers must return a Row when the payload has a name/title, and
None otherwise. The join must skip nan/none/null sentinels that show
up in real GLEIF / TED / ESEF payloads.
"""
from embedding_sink.embed_text import (
    company, authority, contract, disclosure,
    sanctioned_entity, petition, investment_fund, COMPOSERS,
)


def test_company_composes_name_aliases_city_country():
    row = company({
        "gmr_id": "abc-123",
        "name": "Siemens AG",
        "aliases": ["Siemens", "SIE"],
        "city": "Munich",
        "country": "DE",
        "legal_form": "AG",
    })
    assert row is not None
    entity_type, entity_id, text, country, date = row
    assert entity_type == "company"
    assert entity_id == "abc-123"
    assert "Siemens AG" in text
    assert "Siemens · SIE" in text
    assert "Munich" in text
    assert country == "DE"
    assert date is None


def test_company_skips_when_name_missing():
    assert company({"gmr_id": "x", "name": None}) is None
    assert company({"gmr_id": "x", "name": ""}) is None
    assert company({"gmr_id": "x", "name": "  "}) is None


def test_composer_skips_sentinel_placeholders():
    """'nan' / 'None' / 'N/A' appear in the raw GLEIF / TED data — must
    not survive into the embedding text where they'd become noise the
    model would try to associate with the company."""
    row = company({
        "gmr_id": "x", "name": "Real Name",
        "city": "nan", "country": "None", "legal_form": "-",
    })
    _, _, text, country, _ = row
    assert "nan" not in text.lower()
    assert "none" not in text.lower()
    assert text == "Real Name"
    assert country == "None"  # country field is passed through raw for the filter column


def test_authority_composer():
    row = authority({
        "authority_id": "auth-1", "name": "Bundeskanzleramt",
        "city": "Berlin", "country": "DE", "authority_type": "national",
    })
    assert row is not None
    assert row[0] == "authority"
    assert "Bundeskanzleramt" in row[2]


def test_contract_uses_title_and_publication_date():
    row = contract({
        "ted_notice_id": "n1", "title": "Cleaning services for HQ",
        "country": "PT", "publication_date": "2026-05-01",
    })
    assert row is not None
    assert row[0] == "contract"
    assert row[4] == "2026-05-01"


def test_disclosure_maps_system_to_entity_type():
    """eu_cohesion → cohesion; eu_lobbying → lobbying (matches search.py
    handlers which use those keys for facet buckets)."""
    row = disclosure({
        "system": "eu_cohesion", "disclosure_id": "d1",
        "title": "Bike path in Coimbra",
    })
    assert row[0] == "cohesion"

    row = disclosure({
        "system": "eu_lobbying", "disclosure_id": "d2",
        "title": "Big Tech lobbying",
    })
    assert row[0] == "lobbying"


def test_sanctioned_entity_composer():
    row = sanctioned_entity({
        "entity_id": "s1", "name": "Sanctioned Corp",
        "aliases": ["SC", "SanCorp"], "subject_type": "company",
        "sanction_regime": "EU FSD", "nationality": "RU",
        "designation_date": "2026-01-15",
    })
    assert row is not None
    assert "SC · SanCorp" in row[2]
    assert row[3] == "RU"
    assert row[4] == "2026-01-15"


def test_petition_composer():
    row = petition({
        "petition_id": "p1", "title": "Ban PFAS",
        "objectives": ["obj a", "obj b", "obj c", "obj d skipped"],
        "registration_date": "2026-06-01",
    })
    assert row is not None
    # First 3 objectives make it in; 4th is truncated.
    assert "obj a" in row[2] and "obj b" in row[2] and "obj c" in row[2]
    assert "obj d" not in row[2]


def test_investment_fund_composer():
    row = investment_fund({
        "gmr_id": "f1", "name": "Test Fund", "country": "LU",
        "fund_type": "UCITS",
    })
    assert row is not None
    assert row[0] == "fund"


def test_composers_index_matches_module_functions():
    """Every event type in COMPOSERS resolves to a real function.
    Guard against dangling entries after a rename."""
    for event_type, fn in COMPOSERS.items():
        assert callable(fn), f"{event_type} composer is not callable"
        assert event_type.startswith("Upsert")
