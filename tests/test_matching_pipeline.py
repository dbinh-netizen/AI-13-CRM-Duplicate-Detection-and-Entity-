from backend.services.intake import load_all_csv_records
from backend.services.matcher import generate_candidates, generate_exact_candidate_pairs, match_exact
from backend.services.resolver import verify_independent_approver
from backend.services.normalizer import enrich_normalized_fields
import pytest

@pytest.fixture
def exact_candidate_pairs():
    records = [
        {
            "source_key": "ACC-100",
            "entity_type": "COMPANY",
            "legal_name": "Công ty TNHH ABC",
            "tax_code": "0101234567",
            "phone": "0908123456",
            "email": "contact@abc.vn"
        },
        {
            "source_key": "ACC-101",
            "entity_type": "COMPANY",
            "legal_name": "Công ty TNHH ABC",
            "tax_code": "0101234567",
            "phone": "+84908123456",
            "email": "contact@abc.vn"
        }
    ]
    return generate_exact_candidate_pairs(records)

def test_matching_pipeline():
    records = load_all_csv_records()
    assert len(records) > 0
    res = generate_candidates(records)
    assert res["total_candidates"] >= 2

def test_exact_candidate_pair_fixture(exact_candidate_pairs):
    assert exact_candidate_pairs["total_records"] == 2
    assert exact_candidate_pairs["total_candidates"] == 1

    candidate = exact_candidate_pairs["candidates"][0]
    assert candidate["left_source_key"] == "ACC-100"
    assert candidate["right_source_key"] == "ACC-101"
    assert candidate["entity_pool"] == "ACCOUNT"
    assert candidate["proposed_category"] == "SAME_ENTITY"
    assert candidate["review_state"] == "NEW"

def test_match_exact_accepts_normalized_records(exact_candidate_pairs):
    records = [
        enrich_normalized_fields({
            "source_key": "ACC-100",
            "entity_type": "COMPANY",
            "legal_name": "Công ty TNHH ABC",
            "tax_code": "0101234567",
            "phone": "0908123456",
            "email": "contact@abc.vn"
        }),
        enrich_normalized_fields({
            "source_key": "ACC-101",
            "entity_type": "COMPANY",
            "legal_name": "Công ty TNHH ABC",
            "tax_code": "0101234567",
            "phone": "+84908123456",
            "email": "contact@abc.vn"
        })
    ]
    assert match_exact(records) == exact_candidate_pairs

def test_exact_matching_does_not_cross_entity_pools():
    account = enrich_normalized_fields({
        "source_key": "ACC-1",
        "entity_type": "COMPANY",
        "legal_name": "Nguyen Van A",
        "phone": "0908123456"
    })
    contact = enrich_normalized_fields({
        "source_key": "PER-1",
        "entity_type": "CONTACT",
        "full_name": "Nguyen Van A",
        "phone": "0908123456"
    })
    assert generate_exact_candidate_pairs([account, contact])["total_candidates"] == 0

def test_no_self_approval():
    assert verify_independent_approver("user_a", "user_a") is False
    assert verify_independent_approver("user_a", "user_b") is True
