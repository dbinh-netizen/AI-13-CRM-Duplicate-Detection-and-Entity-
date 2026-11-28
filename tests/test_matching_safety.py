import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.canonical.activation_service import CanonicalActivationService
from backend.matching.blocking_engine import (
    IdentifierItem,
    SourceRecordInput,
    clean_email_address,
    clean_phone_number,
    clean_tax_id,
    clean_vietnamese_company_name,
    extract_tax_root,
)
from backend.matching.evidence_builder import EvidenceBuilder
from backend.matching.similarity_scorer import (
    AttributeStatus,
    SimilarityScorer,
)
from backend.review.cluster_service import _has_pairwise_candidate_support
from backend.services.intake import load_all_csv_records
from backend.services.matcher import compare_pair, generate_candidates
from backend.services.normalizer import enrich_normalized_fields

FIXTURES = Path(__file__).parent / "fixtures"


def _load_pair_002():
    return json.loads((FIXTURES / "pair_002.json").read_text(encoding="utf-8"))


def _source_input(record):
    tax_code = clean_tax_id(record["tax_code"])
    role = record["entity_type"]
    name = record["legal_name"]
    phone = clean_phone_number(record["phone"])
    email = clean_email_address(record["email"])
    return SourceRecordInput(
        source_record_id=record.get("record_id", record["source_key"]),
        source_system_code="ERP",
        entity_type="ACCOUNT",
        raw_payload=record,
        identifiers=[
            IdentifierItem(
                identifier_type="TAX_ID",
                identifier_value=tax_code,
                is_primary=True,
                entity_level=role,
            )
        ],
        tax_code=tax_code,
        tax_code_root=extract_tax_root(tax_code),
        primary_name=name,
        normalized_name=clean_vietnamese_company_name(name),
        phone_clean=phone,
        email_clean=email,
        street_ward=record["address"],
    )


def test_pair_002_does_not_resolve_duplicate_source_key_to_the_wrong_company():
    fixture = _load_pair_002()
    anh_duong_a, sao_mai, anh_duong_b = fixture["records"]
    reported_pair = fixture["reported_pair"]

    false_pair = compare_pair(
        enrich_normalized_fields(sao_mai),
        enrich_normalized_fields(anh_duong_b),
    )
    assert false_pair is None

    api_result = generate_candidates(fixture["records"])
    assert api_result["total_candidates"] == 1
    api_candidate = api_result["candidates"][0]
    assert api_candidate["left_source_key"] == "ACC001"
    assert api_candidate["right_source_key"] == "CUS014"
    assert api_candidate["similarity_score"] == 99.0
    assert api_candidate["left_record_id"] == anh_duong_a["record_id"]
    assert api_candidate["right_record_id"] == anh_duong_b["record_id"]
    assert api_candidate["evidence"]
    assert api_candidate["rule_version"]
    assert api_candidate["identity_link_activated"] is False

    records_by_id = {record["record_id"]: record for record in fixture["records"]}
    displayed_left = records_by_id[api_candidate["left_record_id"]]
    assert displayed_left["legal_name"] == anh_duong_a["legal_name"]
    assert displayed_left["legal_name"] != sao_mai["legal_name"]
    assert (
        api_candidate["left_record_id"],
        api_candidate["right_record_id"],
    ) != (
        reported_pair["left_record_id"],
        reported_pair["right_record_id"],
    )

    assert api_candidate["conflict_flags"] == []


def test_csv_preview_resolves_pair_002_using_unique_record_ids():
    records = load_all_csv_records()
    result = generate_candidates(records)
    candidate = next(
        pair
        for pair in result["candidates"]
        if pair["left_source_key"] == "ACC001"
        and pair["right_source_key"] == "CUS014"
    )
    records_by_id = {record["record_id"]: record for record in records}

    assert candidate["left_record_id"] == "accounts_source_a.csv:5"
    assert candidate["right_record_id"] == "accounts_source_b.csv:4"
    assert "Ánh Dương" in records_by_id[candidate["left_record_id"]]["legal_name"]
    assert "Sao Mai" not in records_by_id[candidate["left_record_id"]]["legal_name"]


def test_branch_role_conflict_caps_high_overlap_candidate_below_match_threshold():
    high_overlap_left = {
        "record_id": "head-office",
        "source_key": "HQ-001",
        "entity_type": "COMPANY",
        "legal_name": "Công ty Cổ phần Cơ khí Chính xác Đại Nam",
        "tax_code": "0314892100",
        "phone": "02838112233",
        "email": "shared@dainam-mech.vn",
        "address": "TP.HCM",
    }
    high_overlap_right = {
        "record_id": "branch-001",
        "source_key": "BR-001",
        "entity_type": "BRANCH",
        "legal_name": "Công ty Cổ phần Cơ khí Chính xác Đại Nam",
        "tax_code": "0314892100",
        "phone": "02838112233",
        "email": "shared@dainam-mech.vn",
        "address": "TP.HCM",
    }
    high_overlap_result = compare_pair(
        enrich_normalized_fields(high_overlap_left),
        enrich_normalized_fields(high_overlap_right),
    )
    assert high_overlap_result is not None
    assert high_overlap_result["similarity_score"] == 84.9
    assert high_overlap_result["proposed_category"] == "RELATED_BUT_DISTINCT"
    assert high_overlap_result["identity_link_blocked"] is True
    high_overlap_scored = SimilarityScorer().score_candidate_pair(
        _source_input(high_overlap_left),
        _source_input(high_overlap_right),
    )
    assert high_overlap_scored.attribute_scores["TAX_ID"].status == AttributeStatus.MISMATCH
    assert "ENTITY_LEVEL_MISMATCH" in high_overlap_scored.conflicts_detected
    assert high_overlap_scored.identity_link_blocked is True


def test_authoritative_tax_conflict_with_same_role_blocks_identity_evidence():
    left_record, _, right_record = _load_pair_002()["records"]
    left_record = {
        **left_record,
        "entity_type": "COMPANY",
        "tax_code": "0314892100",
        "legal_name": "Công ty Đại Nam",
    }
    right_record = {
        **right_record,
        "entity_type": "COMPANY",
        "tax_code": "0314892101",
        "legal_name": "Công ty Đại Nam",
        "email": left_record["email"],
    }

    result = SimilarityScorer().score_candidate_pair(
        _source_input(left_record),
        _source_input(right_record),
    )
    assert result.attribute_scores["TAX_ID"].status == AttributeStatus.MISMATCH
    assert "CONFLICT_TAX_ID" in result.conflicts_detected
    assert "SAME_NAME_DIFFERENT_TAX_ID" in result.conflicts_detected
    assert result.identity_link_blocked is True

    evidence = EvidenceBuilder().build_evidence(
        candidate_pair_id="PAIR-IDENTIFIER-CONFLICT",
        left=_source_input(left_record),
        right=_source_input(right_record),
        scoring_result=result,
    )
    assert evidence.conflicts_count >= 1
    assert any(
        item.evidence_direction == "NEGATIVE"
        and item.field_name == "conflict_tax_id"
        for item in evidence.evidence_items
    )
    assert all(item.policy_version == result.rule_version for item in evidence.evidence_items)


def test_cluster_does_not_infer_missing_a_to_c_edge_by_transitivity():
    fixture = json.loads(
        (FIXTURES / "non_transitive_cluster.json").read_text(encoding="utf-8")
    )
    pair_scores = {
        tuple(sorted((pair["left"], pair["right"]))): pair["score"]
        for pair in fixture["candidate_pairs"]
    }

    assert len(fixture["members"]) == 3
    assert _has_pairwise_candidate_support(
        fixture["members"],
        pair_scores,
        fixture["minimum_score"],
    ) is False

    pair_scores[tuple(fixture["missing_direct_pair"])] = 88.0
    assert _has_pairwise_candidate_support(
        fixture["members"],
        pair_scores,
        fixture["minimum_score"],
    ) is True


def test_activation_rejects_a_pair_with_blocking_conflict_evidence():
    evidence_id = uuid4()

    class EvidenceResult:
        def scalar_one_or_none(self):
            return evidence_id

    class Session:
        def execute(self, statement):
            assert statement is not None
            return EvidenceResult()

    pair = SimpleNamespace(id=uuid4())
    with pytest.raises(ValueError, match="cannot activate an identity link"):
        CanonicalActivationService._assert_identity_safe_pair(Session(), pair)
