
import pytest

from backend.services.matcher import compare_pair


def make_record(source_key, name):
    return {
        "source_key": source_key,
        "entity_type": "ACCOUNT",
        "norm_name_accent": name,
        "norm_name_no_accent": name,
        "tax_root": "0123456789",
        "tax_code": "0123456789",
        "norm_phone": "0901234567",
    }


@pytest.mark.parametrize(
    "left_name, right_name",
    [
        ("", ""),
        ("", "CONG TY ABC"),
        ("CONG TY ABC", ""),
        ("   ", "   "),
    ],
)
def test_missing_legal_name_has_no_name_evidence(
    left_name, right_name
):
    """Tên trống không được coi là bằng chứng trùng tên."""

    left = make_record("TEST-A", left_name)
    right = make_record("TEST-B", right_name)

    result = compare_pair(left, right)

    assert not any(
        "Tương đồng Tên" in reason
        for reason in result["reasons"]
    ), f"Invalid name evidence: {result}"


def test_valid_matching_names_have_name_evidence():
    """Tên hợp lệ giống nhau vẫn được tính tương đồng."""

    left = make_record("TEST-A", "CONG TY ABC")
    right = make_record("TEST-B", "CONG TY ABC")

    result = compare_pair(left, right)

    assert any(
        "Tương đồng Tên" in reason
        for reason in result["reasons"]
    )
