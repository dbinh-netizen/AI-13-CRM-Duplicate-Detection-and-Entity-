"""[PHẦN VIỆC: THUẬT TOÁN PHÁT HIỆN TRÙNG LẶP & TẠO CẶP ỨNG VIÊN]"""
from itertools import combinations
from rapidfuzz import fuzz
from backend.config import SUSPECTED_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD, CANDIDATE_CEILING
from backend.services.normalizer import enrich_normalized_fields

MATCHING_RULE_VERSION = "2.0-IDENTITY-SAFETY"


def compare_pair(a: dict, b: dict) -> dict | None:
    entity_type_a = str(a.get("entity_type") or "").strip().upper()
    entity_type_b = str(b.get("entity_type") or "").strip().upper()
    is_contact_a = entity_type_a == "CONTACT"
    is_contact_b = entity_type_b == "CONTACT"
    if is_contact_a != is_contact_b:
        return None

    score = 0.0
    reasons, conflicts, evidence = [], [], []

    def add_evidence(attribute: str, direction: str, left: str, right: str, explanation: str) -> None:
        evidence.append(
            {
                "attribute": attribute,
                "direction": direction,
                "left_value": left or None,
                "right_value": right or None,
                "explanation": explanation,
                "rule_version": MATCHING_RULE_VERSION,
            }
        )

    if entity_type_a and entity_type_b and entity_type_a != entity_type_b:
        conflicts.append("ENTITY_TYPE_MISMATCH")
        add_evidence(
            "ENTITY_TYPE",
            "NEGATIVE",
            entity_type_a,
            entity_type_b,
            "Entity subtypes differ; this pair must not be treated as the same identity.",
        )

    if a.get("tax_root") and b.get("tax_root"):
        tax_a = str(a.get("tax_code") or "").strip()
        tax_b = str(b.get("tax_code") or "").strip()
        if tax_a and tax_a == tax_b:
            score += 45
            reasons.append(f"Trùng khớp Mã số thuế ({a.get('tax_code')})")
            add_evidence("TAX_ID", "POSITIVE", tax_a, tax_b, "Exact authoritative tax identifier match.")
        elif a.get("tax_root") == b.get("tax_root") and a.get("tax_branch") != b.get("tax_branch"):
            score += 35
            reasons.append(f"Cùng MST gốc ({a.get('tax_root')}) nhưng khác mã chi nhánh")
            conflicts.append("PARENT_BRANCH_RELATIONSHIP")
            add_evidence(
                "TAX_ID",
                "NEGATIVE",
                tax_a,
                tax_b,
                "Tax identifiers share a root but identify different legal branches.",
            )
        else:
            conflicts.append("AUTHORITATIVE_IDENTIFIER_CONFLICT")
            add_evidence(
                "TAX_ID",
                "NEGATIVE",
                tax_a,
                tax_b,
                "Authoritative tax identifiers conflict for these records.",
            )
    else:
        add_evidence(
            "TAX_ID",
            "NEUTRAL",
            str(a.get("tax_code") or ""),
            str(b.get("tax_code") or ""),
            "An authoritative tax identifier is missing; no inference is drawn.",
        )

    phone_a = str(a.get("norm_phone") or "")
    phone_b = str(b.get("norm_phone") or "")
    if phone_a and phone_b:
        if phone_a == phone_b:
            score += 30
            reasons.append(f"Trùng SĐT chuẩn hóa ({phone_a})")
            add_evidence("PHONE", "POSITIVE", phone_a, phone_b, "Normalized phone numbers match.")
        else:
            add_evidence("PHONE", "NEGATIVE", phone_a, phone_b, "Normalized phone numbers differ.")
    else:
        add_evidence("PHONE", "NEUTRAL", phone_a, phone_b, "Phone evidence is missing.")

    email_a = str(a.get("norm_email") or "")
    email_b = str(b.get("norm_email") or "")
    if email_a and email_b:
        if email_a == email_b:
            score += 15
            reasons.append(f"Trùng Email ({email_a})")
            add_evidence("EMAIL", "POSITIVE", email_a, email_b, "Normalized email addresses match.")
        else:
            add_evidence("EMAIL", "NEGATIVE", email_a, email_b, "Normalized email addresses differ.")
    else:
        add_evidence("EMAIL", "NEUTRAL", email_a, email_b, "Email evidence is missing.")

    name_a = str(a.get("norm_name_no_accent") or "")
    name_b = str(b.get("norm_name_no_accent") or "")
    if name_a and name_b:
        sim_acc = fuzz.token_sort_ratio(a.get("norm_name_accent", ""), b.get("norm_name_accent", ""))
        sim_no_acc = fuzz.token_sort_ratio(name_a, name_b)
        name_sim = round(0.6 * sim_acc + 0.4 * sim_no_acc, 1)
        if name_sim >= 70:
            score += round((name_sim / 100.0) * 20, 1)
            reasons.append(f"Tương đồng Tên ({name_sim}%)")
            add_evidence("NAME", "POSITIVE", name_a, name_b, f"Name similarity is {name_sim}%.")
        else:
            add_evidence("NAME", "NEGATIVE", name_a, name_b, f"Name similarity is only {name_sim}%.")
    else:
        add_evidence("NAME", "NEUTRAL", name_a, name_b, "Name evidence is missing.")

    score = min(99.0, round(score, 1))
    identity_link_blocked = bool(conflicts)
    if identity_link_blocked:
        score = min(score, max(0.0, HIGH_CONFIDENCE_THRESHOLD - 0.1))
    if score < SUSPECTED_THRESHOLD:
        return None

    if "PARENT_BRANCH_RELATIONSHIP" in conflicts or "ENTITY_TYPE_MISMATCH" in conflicts:
        category = "RELATED_BUT_DISTINCT"
    elif "AUTHORITATIVE_IDENTIFIER_CONFLICT" in conflicts:
        category = "DISTINCT"
    elif score >= HIGH_CONFIDENCE_THRESHOLD and not identity_link_blocked:
        category = "SAME_ENTITY"
    else:
        category = "SUSPECTED_DUPLICATE"

    return {
        "left_record_id": a.get("record_id"),
        "right_record_id": b.get("record_id"),
        "left_source_key": a.get("source_key"),
        "right_source_key": b.get("source_key"),
        "entity_pool": "CONTACT" if is_contact_a else "ACCOUNT",
        "similarity_score": score,
        "proposed_category": category,
        "reasons": reasons,
        "conflicts": conflicts,
        "conflict_flags": conflicts,
        "identity_link_blocked": identity_link_blocked,
        "identity_link_activated": False,
        "evidence": evidence,
        "rule_version": MATCHING_RULE_VERSION,
        "review_state": "NEW"
    }

def generate_candidates(raw_records: list[dict]) -> dict:
    enriched = [enrich_normalized_fields(r) for r in raw_records]
    candidates = []
    for rec_a, rec_b in combinations(enriched, 2):
        res = compare_pair(rec_a, rec_b)
        if res:
            candidates.append(res)
            if len(candidates) >= CANDIDATE_CEILING:
                break
    candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
    return {
        "total_records": len(enriched),
        "total_candidates": len(candidates),
        "candidates": candidates
    }
