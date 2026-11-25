import csv
import io
import re
import hashlib
from typing import Optional
from collections import defaultdict
from .contracts import CSV_CONTRACTS
from .normalizer import (
    normalize_text_exact,
    normalize_text_no_accent,
    normalize_phone,
    normalize_tax_id,
)


def run_intake_pipeline(
    file_bytes: bytes,
    filename: str,
    dataset_type: str,
    batch_id: str = "BATCH_DEFAULT",
    processed_hashes: Optional[set] = None,
) -> dict:
    if dataset_type not in CSV_CONTRACTS:
        raise ValueError(f"Loại dataset không hợp lệ: {dataset_type}")

    contract = CSV_CONTRACTS[dataset_type]
    file_hash = hashlib.sha256(file_bytes).hexdigest()

    if processed_hashes and file_hash in processed_hashes:
        return {
            "status": "SKIPPED_IDEMPOTENT",
            "dataset_type": dataset_type,
            "filename": filename,
            "file_size_bytes": len(file_bytes),
            "batch_id": batch_id,
            "file_hash": file_hash,
            "message": f"File '{filename}' đã được xử lý trước đó.",
            "stats": {
                "total_received": 0,
                "valid_count": 0,
                "quarantine_count": 0,
                "quarantine_reasons": {},
            },
            "valid_records": [],
            "normalized_records": [],
            "quarantine_records": [],
        }

    stream = io.StringIO(file_bytes.decode("utf-8-sig"))
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        raise ValueError(f"File CSV '{filename}' rỗng.")

    missing_cols = set(contract["required_cols"]) - set(reader.fieldnames)
    if missing_cols:
        raise ValueError(f"File '{filename}' sai cấu trúc schema! Thiếu cột: {missing_cols}")

    raw_rows = []
    for idx, row in enumerate(reader, start=2):
        if not any(v.strip() for v in row.values() if v is not None):
            continue
        raw_rows.append({"row_anchor": f"{filename}:line_{idx}", "payload": dict(row)})

    key_col = contract["key_col"]
    allowed_etypes = contract["allowed_entity_types"]
    grouped_by_key = defaultdict(list)
    quarantine_records = []

    for item in raw_rows:
        payload = item["payload"]
        s_key = payload.get(key_col, "").strip()
        e_type = payload.get("entity_type", "").strip()
        s_sys = payload.get("source_system", "").strip()

        if e_type not in allowed_etypes:
            quarantine_records.append({
                "batch_id": batch_id,
                "source_system": s_sys or "UNKNOWN",
                "entity_type": e_type or "UNKNOWN",
                "stable_key": s_key or None,
                "row_anchor": item["row_anchor"],
                "reason": "INVALID_ENTITY_TYPE",
                "raw_payload": payload,
            })
            continue

        if not s_key or not s_sys:
            quarantine_records.append({
                "batch_id": batch_id,
                "source_system": s_sys or "UNKNOWN",
                "entity_type": e_type,
                "stable_key": s_key or None,
                "row_anchor": item["row_anchor"],
                "reason": "MISSING_REQUIRED_KEY",
                "raw_payload": payload,
            })
            continue

        grouped_by_key[s_key].append(item)

    valid_items = []
    business_cols = [
        "full_name",
        "legal_name",
        "trading_name",
        "tax_code",
        "phone",
        "email",
        "address",
        "company_name",
    ]

    for s_key, items in grouped_by_key.items():
        if len(items) == 1:
            valid_items.append((s_key, items[0]))
        else:
            distinct_contents = {
                tuple((c, it["payload"].get(c, "").strip()) for c in business_cols)
                for it in items
            }
            if len(distinct_contents) > 1:
                for it in items:
                    quarantine_records.append({
                        "batch_id": batch_id,
                        "source_system": it["payload"].get("source_system", "").strip(),
                        "entity_type": it["payload"].get("entity_type", "").strip(),
                        "stable_key": s_key,
                        "row_anchor": it["row_anchor"],
                        "reason": "CONFLICTING_DUPLICATE_KEY",
                        "raw_payload": it["payload"],
                    })
            else:
                valid_items.append((s_key, items[0]))
                for it in items[1:]:
                    quarantine_records.append({
                        "batch_id": batch_id,
                        "source_system": it["payload"].get("source_system", "").strip(),
                        "entity_type": it["payload"].get("entity_type", "").strip(),
                        "stable_key": s_key,
                        "row_anchor": it["row_anchor"],
                        "reason": "EXACT_DUPLICATE_ROW",
                        "raw_payload": it["payload"],
                    })

    valid_records = []
    normalized_records = []
    validators = contract.get("optional_rules", {})

    for s_key, item in valid_items:
        payload = item["payload"]
        s_sys = payload.get("source_system", "").strip()
        e_type = payload.get("entity_type", "").strip()
        flags = []

        for col, pattern in validators.items():
            val = payload.get(col, "").strip()
            if val and not re.match(pattern, val):
                flags.append(f"INVALID_{col.upper()}")

        valid_records.append({
            "batch_id": batch_id,
            "source_system": s_sys,
            "entity_type": e_type,
            "stable_key": s_key,
            "row_anchor": item["row_anchor"],
            "field_quality_flags": flags,
            "raw_payload": payload,
        })

        primary_name = (
            payload.get("full_name", "")
            if e_type == "CONTACT"
            else payload.get("legal_name", "")
        )
        addr = payload.get("address", "")

        normalized_records.append({
            "batch_id": batch_id,
            "source_system": s_sys,
            "entity_type": e_type,
            "stable_key": s_key,
            "row_anchor": item["row_anchor"],
            "norm_name_exact": normalize_text_exact(primary_name),
            "norm_name_no_accent": normalize_text_no_accent(primary_name),
            "norm_tax_code": normalize_tax_id(payload.get("tax_code", "")),
            "norm_phone": normalize_phone(payload.get("phone", "")),
            "norm_email": payload.get("email", "").strip().lower(),
            "norm_address_no_accent": normalize_text_no_accent(addr),
        })

    reason_counts = defaultdict(int)
    for q in quarantine_records:
        reason_counts[q["reason"]] += 1

    return {
        "status": "SUCCESS",
        "dataset_type": dataset_type,
        "filename": filename,
        "file_size_bytes": len(file_bytes),
        "batch_id": batch_id,
        "file_hash": file_hash,
        "stats": {
            "total_received": len(raw_rows),
            "valid_count": len(valid_records),
            "quarantine_count": len(quarantine_records),
            "quarantine_reasons": dict(reason_counts),
        },
        "valid_records": valid_records,
        "normalized_records": normalized_records,
        "quarantine_records": quarantine_records,
    }