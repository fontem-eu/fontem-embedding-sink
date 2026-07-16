"""Tests for the shared procurement-integrity indicators."""
from fontem_event_schemas.integrity import contract_red_flags


def test_single_bidder_open_competitive():
    """A single bidder on an open MEAT procedure flags only single-bidder."""
    f = contract_red_flags({"tenders_received": 1, "procedure_type": "open",
                            "award_criterion_type": "meat"})
    assert f["is_single_bidder"] is True
    assert f["is_non_open"] is False
    assert f["is_no_call"] is False
    assert f["is_price_only"] is False
    assert f["integrity_red_flags"] == 1   # only single-bidder fired


def test_direct_award_price_only_stacks_flags():
    """A single-bidder, no-call, price-only award trips all four flags."""
    f = contract_red_flags({"tenders_received": 1, "procedure_type": "neg-wo-call",
                            "award_criterion_type": "price"})
    assert f["is_single_bidder"] is True
    assert f["is_non_open"] is True
    assert f["is_no_call"] is True
    assert f["is_price_only"] is True
    assert f["integrity_red_flags"] == 4   # all four fired


def test_clean_competitive_contract():
    """A 5-bidder open MEAT contract trips nothing."""
    f = contract_red_flags({"tenders_received": 5, "procedure_type": "open",
                            "award_criterion_type": "meat"})
    assert f["integrity_red_flags"] == 0


def test_absent_inputs_omit_flags():
    """Unknown inputs omit their flags entirely (unknown != not-flagged)."""
    # Unknown bidder count / procedure / criterion → no flag asserted.
    f = contract_red_flags({"title": "x"})
    assert "is_single_bidder" not in f
    assert "is_non_open" not in f
    assert "is_price_only" not in f
    assert "integrity_red_flags" not in f   # nothing to count


def test_partial_inputs_count_only_present():
    """The red-flag count covers only the flags whose inputs are present."""
    # Only procedure known → only procedure flags + their count.
    f = contract_red_flags({"procedure_type": "open"})
    assert f["is_non_open"] is False and f["is_no_call"] is False
    assert "is_single_bidder" not in f
    assert f["integrity_red_flags"] == 0
