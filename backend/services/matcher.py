"""[PHẦN VIỆC: THUẬT TOÁN PHÁT HIỆN TRÙNG LẶP & TẠO CẶP ỨNG VIÊN]

Interface bàn giao cho Backend (W04, chỉ exact matching):
    match_exact(normalized_records) -> {"total_records", "total_candidates", "candidates"}
Fuzzy matching CHƯA triển khai (đang tắt, chờ review baseline).
"""
from collections import defaultdict
from itertools import combinations
from rapidfuzz import fuzz
from backend.config import SUSPECTED_THRESHOLD, HIGH_CONFIDENCE_THRESHOLD, CANDIDATE_CEILING
from backend.services.normalizer import enrich_normalized_fields

# Khối (block) có quá nhiều bản ghi thường là dữ liệu rác (vd: SĐT dùng chung) -> bỏ qua
MAX_BLOCK_SIZE = 200


def compare_pair(a: dict, b: dict, enable_fuzzy: bool = False) -> dict | None:
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

    if enable_fuzzy:
        # TODO: chỉ bật sau khi baseline fuzzy được review
        sim_acc = fuzz.token_sort_ratio(a.get("norm_name_accent", ""), b.get("norm_name_accent", ""))
        sim_no_acc = fuzz.token_sort_ratio(a.get("norm_name_no_accent", ""), b.get("norm_name_no_accent", ""))
        name_sim = round(0.6 * sim_acc + 0.4 * sim_no_acc, 1)
        if name_sim >= 70:
            score += round((name_sim / 100.0) * 20, 1)
            reasons.append(f"Tương đồng Tên ({name_sim}%)")
    else:
        name = a.get("norm_name_no_accent")
        if name and name == b.get("norm_name_no_accent"):
            score += 20
            reasons.append(f"Trùng khớp Tên chuẩn hóa ({name})")

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
        "review_state": "NEW",
    }


def _blocked_index_pairs(records: list[dict]) -> set[tuple[int, int]]:
    """Blocking: chỉ ghép các bản ghi có chung MST gốc / SĐT / Email chuẩn hóa."""
    blocks = defaultdict(list)
    for idx, r in enumerate(records):
        for key_type, value in (
            ("tax_root", r.get("tax_root")),
            ("phone", r.get("norm_phone")),
            ("email", r.get("norm_email")),
        ):
            if value:
                blocks[(key_type, value)].append(idx)
    pairs: set[tuple[int, int]] = set()
    for idxs in blocks.values():
        if 2 <= len(idxs) <= MAX_BLOCK_SIZE:
            pairs.update(combinations(idxs, 2))  # idxs tăng dần -> i < j
    return pairs


def match_exact(normalized_records: list[dict]) -> dict:
    """INTERFACE CHÍNH: nhận normalized records (đã qua enrich_normalized_fields)."""
    candidates = []
    for i, j in sorted(_blocked_index_pairs(normalized_records)):
        res = compare_pair(normalized_records[i], normalized_records[j])
        if res:
            candidates.append(res)
    candidates.sort(key=lambda x: x["similarity_score"], reverse=True)
    candidates = candidates[:CANDIDATE_CEILING]
    return {
        "total_records": len(normalized_records),
        "total_candidates": len(candidates),
        "candidates": candidates,
    }


def generate_candidates(raw_records: list[dict]) -> dict:
    """Giữ tương thích cũ: chuẩn hóa rồi gọi match_exact."""
    return match_exact([enrich_normalized_fields(r) for r in raw_records])


def generate_exact_candidate_pairs(records: list[dict]) -> dict:
    """Public W04 interface: nhận raw hoặc normalized records."""
    return match_exact([enrich_normalized_fields(r) for r in records])


generate_candidate_pairs = generate_exact_candidate_pairs