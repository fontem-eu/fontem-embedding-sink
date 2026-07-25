"""Unit tests for the embed_text composers.

Composers must return a Row when the payload has a name/title, and
None otherwise. The join must skip nan/none/null sentinels that show
up in real GLEIF / TED / ESEF payloads.
"""
from embedding_sink.embed_text import (
    company, authority, authority_translations, contract, disclosure,
    sanctioned_entity, petition, investment_fund, COMPOSERS,
)


def test_company_composes_name_aliases_city_country():
    """Name, aliases and city/country/legal_form context all land in the text."""
    row = company({
        "gmr_id": "abc-123",
        "name": "Siemens AG",
        "aliases": ["Siemens", "SIE"],
        "city": "Munich",
        "country": "DE",
        "legal_form": "AG",
    })
    assert row is not None
    entity_type, entity_id, text, country, date, *_ = row
    assert entity_type == "company"
    assert entity_id == "abc-123"
    assert "Siemens AG" in text
    assert "Siemens · SIE" in text
    assert "Munich" in text
    assert country == "DE"
    assert date is None


def test_company_skips_when_name_missing():
    """None / empty / whitespace-only names compose to None (event skipped)."""
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
    _, _, text, country, *_ = row
    assert "nan" not in text.lower()
    assert "none" not in text.lower()
    assert text == "Real Name"
    assert country == "None"  # country field is passed through raw for the filter column


def test_authority_composer():
    """UpsertAuthority composes name + context into an authority row."""
    row = authority({
        "authority_id": "auth-1", "name": "Bundeskanzleramt",
        "city": "Berlin", "country": "DE", "authority_type": "national",
    })
    assert row is not None
    assert row[0] == "authority"
    assert "Bundeskanzleramt" in row[2]


def test_authority_translations_folds_name_and_translations():
    """TranslateAuthorityName -> embed_text carries the source name AND
    every translation, so name_lex + vector match translated names."""
    row = authority_translations({
        "authority_id": "auth-7",
        "name": "Kraśnickie Przedsiębiorstwo Wodociągów",
        "source_lang": "pl",
        "translations": {
            "de": "Kraśnicker Wasserunternehmen",
            "en": "Kraśnik Water Company",
        },
    })
    assert row is not None
    assert row[0] == "authority"
    assert row[1] == "auth-7"
    assert "Kraśnickie" in row[2]
    assert "Wasserunternehmen" in row[2]
    assert "Water Company" in row[2]
    # text-only enrichment: filter columns are None (sink partial upsert
    # leaves the authority's country/nuts/sector/meta untouched).
    assert row[3] is None and row[5] is None and row[6] is None and row[7] is None


def test_authority_translations_empty_is_skipped():
    """No name and no translations -> nothing to embed."""
    assert authority_translations({
        "authority_id": "auth-8", "name": "", "translations": {},
    }) is None


def test_contract_uses_title_and_publication_date():
    """UpsertContract keys on title and carries publication_date."""
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
    """Aliases, nationality and designation_date survive into the row."""
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
    """Title plus at most three objectives make up the petition text."""
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
    """UpsertInvestmentFund composes into a fund row."""
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
        # Almost all embeddable events are Upsert*; TranslateAuthorityName
        # is the one text-only enrichment event (routed to the partial
        # upsert in the sink).
        assert event_type.startswith("Upsert") or event_type == "TranslateAuthorityName"


# ---------- advanced-filter fields (nuts, sector, meta jsonb) ----------

def test_contract_projects_nuts_sector_and_value_tier_meta():
    """Contract composer pulls NUTS + CPV-top-2 as sector + value_tier
    into meta. Filter surface for the advanced-search panel."""
    row = contract({
        "ted_notice_id": "TED-1", "title": "Cleaning services HQ",
        "country": "PT", "nuts": "PT18",
        "cpv": "90910000", "value_eur": 350_000,
        "authority_id": "AUTH-42", "publication_date": "2026-05-01",
    })
    assert row is not None
    # positional: (type, id, text, country, event_date, nuts, sector, meta)
    assert row[5] == "PT18"
    assert row[6] == "90"                # CPV top-2 = "sewage/refuse services"
    assert row[7]["value_tier"] == "M"   # 100k-1M
    assert row[7]["value_eur"] == 350_000
    assert row[7]["authority_id"] == "AUTH-42"


def test_authority_projects_nuts_and_authority_type_as_sector():
    """UpsertAuthority: nuts direct + authority_type as sector; meta carries url/national_id."""
    row = authority({
        "authority_id": "AUTH-9", "name": "Ministry of Defence",
        "country": "IE", "nuts": "IE04", "authority_type": "ministry",
        "national_id": "9999", "url": "https://gov.ie/def", "city": "Dublin",
    })
    assert row is not None
    assert row[5] == "IE04"
    assert row[6] == "ministry"
    assert row[7]["national_id"] == "9999"
    assert row[7]["url"] == "https://gov.ie/def"


def test_disclosure_cohesion_pulls_nuts_from_details():
    """eu_cohesion projects put NUTS + theme in payload.details. Kohesio
    ships the key as `nuts_code`; the legacy `nuts` key is still accepted
    so old loader test fixtures keep working."""
    row = disclosure({
        "system": "eu_cohesion", "disclosure_id": "COH-1",
        "title": "Rail electrification NUTS PT16",
        "filed_date": "2026-05-01",
        "details": {"nuts_code": "PT16", "theme_code": "TO7", "country": "PT"},
    })
    assert row is not None
    assert row[0] == "cohesion"
    assert row[3] == "PT"    # country pulled from details
    assert row[5] == "PT16"
    assert row[6] == "TO7"

    # legacy key still works
    row_legacy = disclosure({
        "system": "eu_cohesion", "disclosure_id": "COH-2",
        "title": "Legacy fixture",
        "details": {"nuts": "PT17"},
    })
    assert row_legacy is not None
    assert row_legacy[5] == "PT17"


def test_company_leaves_nuts_none_but_populates_meta():
    """Companies don't ship a NUTS field yet; ensure it stays None
    and doesn't accidentally get filled from unrelated fields."""
    row = company({
        "gmr_id": "abc", "name": "Siemens AG",
        "country": "DE", "legal_form": "AG",
        "lei": "LEI-DE-1234567890",
    })
    assert row is not None
    assert row[5] is None                          # no nuts
    assert row[6] == "AG"                          # legal_form as coarse sector
    assert row[7]["lei"] == "LEI-DE-1234567890"


def test_meta_drops_none_and_empty_values():
    """`_compact_meta` shouldn't preserve None/empty entries — they'd
    bloat the jsonb column without adding filter or display value."""
    row = investment_fund({
        "gmr_id": "f1", "name": "Test Fund", "country": "LU",
        "fund_type": None, "lei": "", "legal_form": None,
    })
    assert row is not None
    # All optionals None/empty -> meta itself becomes None
    assert row[7] is None


def test_contract_value_tier_boundaries():
    """Boundary check on the tier bucketing."""
    tests = [(50_000, "S"), (100_000, "M"), (999_999, "M"),
             (1_000_000, "L"), (10_000_000, "XL")]
    for value, expected in tests:
        row = contract({
            "ted_notice_id": f"T-{value}", "title": "x",
            "country": "PT", "value_eur": value,
        })
        assert row is not None
        assert row[7]["value_tier"] == expected, f"value={value}"
