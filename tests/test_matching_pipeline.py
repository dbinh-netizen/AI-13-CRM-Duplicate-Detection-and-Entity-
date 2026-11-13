from backend.services.intake import load_all_csv_records
from backend.services.matcher import generate_candidates
from backend.services.resolver import verify_independent_approver

def test_matching_pipeline():
    records = load_all_csv_records()
    assert len(records) > 0
    res = generate_candidates(records)
    assert res["total_candidates"] >= 2

def test_no_self_approval():
    assert verify_independent_approver("user_a", "user_a") is False
    assert verify_independent_approver("user_a", "user_b") is True
