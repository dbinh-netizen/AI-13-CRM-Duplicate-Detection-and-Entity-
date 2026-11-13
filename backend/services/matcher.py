"""[PHẦN VIỆC: THUẬT TOÁN PHÁT HIỆN TRÙNG LẶP & TẠO CẶP ỨNG VIÊN]"""
from itertools import combinations
from rapidfuzz import fuzz
from backend.config import SUSPECTED_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD, CANDIDATE_CEILING
from backend.services.normalizer import enrich_normalized_fields

def compare_pair(a: dict, b: dict) -> dict | None:
    is_contact_a = a.get("entity_type") == "CONTACT"
    is_contact_b = b.get("entity_type") == "CONTACT"
    if is_contact_a != is_contact_b:
        return None

    score = 0.0
    reasons, conflicts = [], []

    if a.get("tax_root") and b.get("tax_root"):
        if a.get("tax_code") == b.get("tax_code"):
            score += 45
            reasons.append(f"Trùng khớp Mã số thuế ({a.get('tax_code')})")
        elif a.get("tax_root") == b.get("tax_root") and a.get("tax_branch") != b.get("tax_branch"):
            score += 35
            reasons.append(f"Cùng MST gốc ({a.get('tax_root')}) nhưng khác mã chi nhánh")
            conflicts.append("PARENT_BRANCH_RELATIONSHIP")

    if a.get("norm_phone") and a.get("norm_phone") == b.get("norm_phone"):
        score += 30
        reasons.append(f"Trùng SĐT chuẩn hóa ({a.get('norm_phone')})")

    if a.get("norm_email") and a.get("norm_email") == b.get("norm_email"):
        score += 15
        reasons.append(f"Trùng Email ({a.get('norm_email')})")

    sim_acc = fuzz.token_sort_ratio(a.get("norm_name_accent", ""), b.get("norm_name_accent", ""))
    sim_no_acc = fuzz.token_sort_ratio(a.get("norm_name_no_accent", ""), b.get("norm_name_no_accent", ""))
    name_sim = round(0.6 * sim_acc + 0.4 * sim_no_acc, 1)
    if name_sim >= 70:
        score += round((name_sim / 100.0) * 20, 1)
        reasons.append(f"Tương đồng Tên ({name_sim}%)")

    score = min(99.0, round(score, 1))
    if score < SUSPECTED_THRESHOLD:
        return None

    category = "RELATED_BUT_DISTINCT" if "PARENT_BRANCH_RELATIONSHIP" in conflicts else (
        "SAME_ENTITY" if score >= HIGH_CONFIDENCE_THRESHOLD else "SUSPECTED_DUPLICATE"
    )

    return {
        "left_source_key": a.get("source_key"),
        "right_source_key": b.get("source_key"),
        "entity_pool": "CONTACT" if is_contact_a else "ACCOUNT",
        "similarity_score": score,
        "proposed_category": category,
        "reasons": reasons,
        "conflicts": conflicts,
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
