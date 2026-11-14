"""Migrate legacy data into reconciled target schema

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-14

"""
import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text
from backend.models.base import GUIDType, ISOUtcDateTime

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration_0008")

# Deterministic IDs for migration artifacts
ACCOUNT_RUN_ID = str(uuid.UUID("00000008-0000-0000-0000-000000000001"))
CONTACT_RUN_ID = str(uuid.UUID("00000008-0000-0000-0000-000000000002"))
BASELINE_POLICY_ID = str(uuid.UUID("00000008-0000-0000-0000-000000000003"))
CRM_A_ID = str(uuid.UUID("00000008-0000-0000-0000-00000000000a"))
CRM_B_ID = str(uuid.UUID("00000008-0000-0000-0000-00000000000b"))
CRM_C_ID = str(uuid.UUID("00000008-0000-0000-0000-00000000000c"))
BATCH_CRM_A_ID = str(uuid.UUID("00000008-0000-0000-0001-00000000000a"))
BATCH_CRM_B_ID = str(uuid.UUID("00000008-0000-0000-0001-00000000000b"))
BATCH_CRM_C_ID = str(uuid.UUID("00000008-0000-0000-0001-00000000000c"))
BATCH_UNMAPPED_ID = str(uuid.UUID("00000008-0000-0000-0001-000000000099"))

def upgrade() -> None:
    conn = op.get_bind()
    now_iso = datetime.now(timezone.utc).isoformat()

    # -------------------------------------------------------------
    # 0. IDEMPOTENCY GUARD: State machine check
    # -------------------------------------------------------------
    check_runs_query = text(
        "SELECT run_code, status FROM matching_runs "
        "WHERE run_code IN ('MIG-0008-HISTORICAL-PAIRS-ACCOUNT', 'MIG-0008-HISTORICAL-PAIRS-CONTACT')"
    )
    existing_runs = conn.execute(check_runs_query).fetchall()
    completed_runs = {r[0]: r[1] for r in existing_runs if r[1] == "COMPLETED"}

    if "MIG-0008-HISTORICAL-PAIRS-ACCOUNT" in completed_runs and "MIG-0008-HISTORICAL-PAIRS-CONTACT" in completed_runs:
        logger.info("Migration 0008: Both historical matching runs already COMPLETED. Skipping idempotent migration.")
        return

    # -------------------------------------------------------------
    # 1. BASELINE NORMALIZATION POLICY
    # -------------------------------------------------------------
    policy_check = conn.execute(
        text("SELECT id FROM normalization_policies WHERE id = :id"), {"id": BASELINE_POLICY_ID}
    ).fetchone()
    if not policy_check:
        conn.execute(
            text(
                "INSERT INTO normalization_policies (id, policy_name, version_number, status, config_payload, effective_from, created_at) "
                "VALUES (:id, 'LEGACY_MIGRATION_BASELINE', 1, 'ACTIVE', :config, :now, :now)"
            ),
            {
                "id": BASELINE_POLICY_ID,
                "config": json.dumps({"legacy_reconciliation": True, "rules": ["exact_name", "tax_code", "phone"]}),
                "now": now_iso,
            },
        )

    # -------------------------------------------------------------
    # 2. SOURCE SYSTEMS SETUP (CRM_A, CRM_B, CRM_C)
    # -------------------------------------------------------------
    sources = [
        (CRM_A_ID, "CRM_A", "Legacy CRM System A (Enterprise Accounts)", "LEGACY_CRM", "ACCOUNT"),
        (CRM_B_ID, "CRM_B", "Legacy CRM System B (Regional Branches)", "LEGACY_CRM", "ACCOUNT"),
        (CRM_C_ID, "CRM_C", "Legacy CRM System C (Contact Directory)", "LEGACY_CRM", "CONTACT"),
    ]
    for sys_id, code, name, stype, pool in sources:
        exists = conn.execute(text("SELECT id FROM source_systems WHERE source_code = :code"), {"code": code}).fetchone()
        if not exists:
            conn.execute(
                text(
                    "INSERT INTO source_systems (id, source_code, source_name, system_type, entity_type, is_active, created_at, updated_at) "
                    "VALUES (:id, :code, :name, :stype, :pool, 1, :now, :now)"
                ),
                {"id": sys_id, "code": code, "name": name, "stype": stype, "pool": pool, "now": now_iso},
            )

    # Resolve actual system IDs in case they existed prior
    sys_map = {}
    for row in conn.execute(text("SELECT source_code, id, entity_type FROM source_systems")).fetchall():
        sys_map[row[0]] = {"id": str(row[1]), "pool": row[2]}

    # -------------------------------------------------------------
    # 3. IMPORT BATCHES SETUP
    # -------------------------------------------------------------
    batches = [
        (BATCH_CRM_A_ID, "BATCH-LEGACY-0008-CRM-A", sys_map["CRM_A"]["id"], "LEGACY_MIGRATION", "legacy_source_records/CRM_A", "COMPLETED"),
        (BATCH_CRM_B_ID, "BATCH-LEGACY-0008-CRM-B", sys_map["CRM_B"]["id"], "LEGACY_MIGRATION", "legacy_source_records/CRM_B", "COMPLETED"),
        (BATCH_CRM_C_ID, "BATCH-LEGACY-0008-CRM-C", sys_map["CRM_C"]["id"], "LEGACY_MIGRATION", "legacy_source_records/CRM_C", "COMPLETED"),
        (BATCH_UNMAPPED_ID, "BATCH-LEGACY-0008-UNMAPPED", None, "UNMAPPED_QUARANTINE", "legacy_source_records/unmapped", "QUARANTINED"),
    ]
    for b_id, b_code, s_id, b_type, f_name, b_status in batches:
        exists = conn.execute(text("SELECT id FROM import_batches WHERE batch_code = :code"), {"code": b_code}).fetchone()
        if not exists:
            checksum = hashlib.sha256(b_code.encode("utf-8")).hexdigest()
            conn.execute(
                text(
                    "INSERT INTO import_batches ("
                    "id, batch_code, source_system_id, batch_type, file_name, file_checksum, file_size_bytes, "
                    "total_rows_received, total_rows_valid, total_rows_quarantined, total_rows_rejected, status, "
                    "imported_at, created_at"
                    ") VALUES (:id, :code, :sid, :btype, :fname, :chk, 0, 0, 0, 0, 0, :status, :now, :now)"
                ),
                {
                    "id": b_id,
                    "code": b_code,
                    "sid": s_id,
                    "btype": b_type,
                    "fname": f_name,
                    "chk": checksum,
                    "status": b_status,
                    "now": now_iso,
                },
            )

    # -------------------------------------------------------------
    # 4. MATCHING RUNS INITIALIZATION (RUNNING state)
    # -------------------------------------------------------------
    matching_runs_to_init = [
        (ACCOUNT_RUN_ID, "MIG-0008-HISTORICAL-PAIRS-ACCOUNT", "ACCOUNT", "Legacy candidate pairs consolidation (ACCOUNT pool)"),
        (CONTACT_RUN_ID, "MIG-0008-HISTORICAL-PAIRS-CONTACT", "CONTACT", "Legacy candidate pairs consolidation (CONTACT pool)"),
    ]
    for run_id, run_code, pool, notes in matching_runs_to_init:
        exists = conn.execute(text("SELECT id FROM matching_runs WHERE run_code = :code"), {"code": run_code}).fetchone()
        if not exists:
            conn.execute(
                text(
                    "INSERT INTO matching_runs ("
                    "id, run_code, entity_pool, status, policy_id, total_candidates, ceiling_breached, "
                    "started_at, completed_at, executed_by, notes, created_at"
                    ") VALUES (:id, :code, :pool, 'RUNNING', :pol_id, 0, 0, :now, NULL, NULL, :notes, :now)"
                ),
                {"id": run_id, "code": run_code, "pool": pool, "pol_id": BASELINE_POLICY_ID, "now": now_iso, "notes": notes},
            )

    # Link run_sources
    run_source_links = [
        (ACCOUNT_RUN_ID, BATCH_CRM_A_ID, sys_map["CRM_A"]["id"]),
        (ACCOUNT_RUN_ID, BATCH_CRM_B_ID, sys_map["CRM_B"]["id"]),
        (CONTACT_RUN_ID, BATCH_CRM_C_ID, sys_map["CRM_C"]["id"]),
    ]
    for m_run_id, b_id, s_id in run_source_links:
        exists = conn.execute(
            text("SELECT id FROM run_sources WHERE matching_run_id = :mid AND import_batch_id = :bid"),
            {"mid": m_run_id, "bid": b_id},
        ).fetchone()
        if not exists:
            conn.execute(
                text(
                    "INSERT INTO run_sources (id, matching_run_id, import_batch_id, source_system_id, snapshot_cutoff, is_complete, created_at) "
                    "VALUES (:id, :mid, :bid, :sid, :now, 1, :now)"
                ),
                {"id": str(uuid.uuid4()), "mid": m_run_id, "bid": b_id, "sid": s_id, "now": now_iso},
            )

    # -------------------------------------------------------------
    # 5. MIGRATE LEGACY SOURCE RECORDS
    # -------------------------------------------------------------
    has_legacy_sources = False
    try:
        conn.execute(text("SELECT 1 FROM legacy_source_records LIMIT 1"))
        has_legacy_sources = True
    except Exception:
        has_legacy_sources = False

    legacy_records = []
    if has_legacy_sources:
        legacy_records = conn.execute(
            text("SELECT id, source_system, source_key, entity_type, name, tax_code, phone, email, address, imported_at FROM legacy_source_records")
        ).fetchall()

    key_counts = {}
    for r in legacy_records:
        k = r[2]
        key_counts[k] = key_counts.get(k, 0) + 1

    migrated_keys = {}  # source_key -> (source_record_id, pool, source_system_code)
    batch_counts = {
        BATCH_CRM_A_ID: {"valid": 0, "quar": 0, "rej": 0, "recv": 0},
        BATCH_CRM_B_ID: {"valid": 0, "quar": 0, "rej": 0, "recv": 0},
        BATCH_CRM_C_ID: {"valid": 0, "quar": 0, "rej": 0, "recv": 0},
        BATCH_UNMAPPED_ID: {"valid": 0, "quar": 0, "rej": 0, "recv": 0},
    }

    batch_by_source = {
        "CRM_A": BATCH_CRM_A_ID,
        "CRM_B": BATCH_CRM_B_ID,
        "CRM_C": BATCH_CRM_C_ID,
    }

    for row_idx, r in enumerate(legacy_records, start=1):
        l_id, l_sys, l_key, l_type, l_name, l_tax, l_phone, l_email, l_addr, l_imported = r
        target_batch = batch_by_source.get(l_sys, BATCH_UNMAPPED_ID)
        batch_counts[target_batch]["recv"] += 1

        payload_dict = {
            "name": l_name,
            "tax_code": l_tax,
            "phone": l_phone,
            "email": l_email,
            "address": l_addr,
        }
        payload_dict = {k: v for k, v in payload_dict.items() if v is not None}
        payload_json = json.dumps(payload_dict)
        payload_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()

        # Check missing source key
        if not l_key or not str(l_key).strip():
            batch_counts[target_batch]["rej"] += 1
            conn.execute(
                text(
                    "INSERT INTO batch_row_results ("
                    "id, import_batch_id, row_number, source_key, row_status, "
                    "validation_errors, quarantine_reason, raw_row_hash, raw_row_data, source_record_id, created_at"
                    ") VALUES (:id, :bid, :rnum, :skey, 'REJECTED', :verrs, :qreason, :rhash, :rdata, NULL, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "bid": target_batch,
                    "rnum": row_idx,
                    "skey": str(l_key) if l_key else None,
                    "verrs": json.dumps(["MISSING_SOURCE_KEY"]),
                    "qreason": "Persistent identity anchor cannot be established",
                    "rhash": payload_hash,
                    "rdata": payload_json,
                    "now": now_iso,
                },
            )
            continue

        # Check unmapped source system
        if l_sys not in sys_map:
            batch_counts[BATCH_UNMAPPED_ID]["quar"] += 1
            conn.execute(
                text(
                    "INSERT INTO batch_row_results ("
                    "id, import_batch_id, row_number, source_key, row_status, "
                    "validation_errors, quarantine_reason, raw_row_hash, raw_row_data, source_record_id, created_at"
                    ") VALUES (:id, :bid, :rnum, :skey, 'QUARANTINED', :verrs, :qreason, :rhash, :rdata, NULL, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "bid": BATCH_UNMAPPED_ID,
                    "rnum": row_idx,
                    "skey": str(l_key),
                    "verrs": json.dumps(["INVALID_SOURCE_SYSTEM"]),
                    "qreason": "Value missing or unmapped in source system registry",
                    "rhash": payload_hash,
                    "rdata": payload_json,
                    "now": now_iso,
                },
            )
            continue

        # Check duplicate source key in legacy
        if key_counts[l_key] > 1:
            batch_counts[target_batch]["quar"] += 1
            conn.execute(
                text(
                    "INSERT INTO batch_row_results ("
                    "id, import_batch_id, row_number, source_key, row_status, "
                    "validation_errors, quarantine_reason, raw_row_hash, raw_row_data, source_record_id, created_at"
                    ") VALUES (:id, :bid, :rnum, :skey, 'QUARANTINED', :verrs, :qreason, :rhash, :rdata, NULL, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "bid": target_batch,
                    "rnum": row_idx,
                    "skey": str(l_key),
                    "verrs": json.dumps(["DUPLICATE_SOURCE_KEY_IN_SOURCE"]),
                    "qreason": "Key appears multiple times in legacy intake",
                    "rhash": payload_hash,
                    "rdata": payload_json,
                    "now": now_iso,
                },
            )
            continue

        # Map entity pool & subtype
        mapped_pool = None
        mapped_subtype = None
        if l_type in ("COMPANY", "ENTERPRISE", "ORGANIZATION"):
            mapped_pool = "ACCOUNT"
            mapped_subtype = "COMPANY"
        elif l_type in ("BRANCH", "OFFICE", "FACTORY"):
            mapped_pool = "ACCOUNT"
            mapped_subtype = "BRANCH"
        elif l_type in ("SITE", "STORE", "WAREHOUSE"):
            mapped_pool = "ACCOUNT"
            mapped_subtype = "SITE"
        elif l_type in ("CONTACT", "PERSON", "INDIVIDUAL", "LEAD"):
            mapped_pool = "CONTACT"
            mapped_subtype = "PERSON"

        expected_pool = sys_map[l_sys]["pool"]
        if not mapped_pool or mapped_pool != expected_pool:
            batch_counts[target_batch]["quar"] += 1
            conn.execute(
                text(
                    "INSERT INTO batch_row_results ("
                    "id, import_batch_id, row_number, source_key, row_status, "
                    "validation_errors, quarantine_reason, raw_row_hash, raw_row_data, source_record_id, created_at"
                    ") VALUES (:id, :bid, :rnum, :skey, 'QUARANTINED', :verrs, :qreason, :rhash, :rdata, NULL, :now)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "bid": target_batch,
                    "rnum": row_idx,
                    "skey": str(l_key),
                    "verrs": json.dumps(["UNRESOLVED_ENTITY_TYPE_AMBIGUITY"]),
                    "qreason": "Source system expects pool parity but record contains contradictory or insufficient evidence.",
                    "rhash": payload_hash,
                    "rdata": payload_json,
                    "now": now_iso,
                },
            )
            continue

        # Migrated Valid Row
        sr_id = str(uuid.uuid4())
        srv_id = str(uuid.uuid4())
        rec_sys_id = sys_map[l_sys]["id"]

        # Insert source_records
        conn.execute(
            text(
                "INSERT INTO source_records ("
                "id, source_system_id, entity_type, source_key, import_batch_id, entity_subtype, status, record_payload, created_at, updated_at"
                ") VALUES (:id, :sid, :pool, :skey, :bid, :subt, 'ACTIVE', :payload, :now, :now)"
            ),
            {
                "id": sr_id,
                "sid": rec_sys_id,
                "pool": mapped_pool,
                "skey": l_key,
                "bid": target_batch,
                "subt": mapped_subtype,
                "payload": payload_json,
                "now": now_iso,
            },
        )

        # Insert source_record_versions (v1)
        conn.execute(
            text(
                "INSERT INTO source_record_versions ("
                "id, source_record_id, version_number, import_batch_id, row_anchor_hash, raw_payload, checksum, effective_from, is_current, created_at"
                ") VALUES (:id, :srid, 1, :bid, :anchor, :payload, :chk, :now, 1, :now)"
            ),
            {
                "id": srv_id,
                "srid": sr_id,
                "bid": target_batch,
                "anchor": payload_hash,
                "payload": payload_json,
                "chk": payload_hash,
                "now": now_iso,
            },
        )

        # Record accepted result in batch_row_results
        batch_counts[target_batch]["valid"] += 1
        conn.execute(
            text(
                "INSERT INTO batch_row_results ("
                "id, import_batch_id, row_number, source_key, row_status, "
                "validation_errors, quarantine_reason, raw_row_hash, raw_row_data, source_record_id, created_at"
                ") VALUES (:id, :bid, :rnum, :skey, 'MIGRATED', NULL, NULL, :rhash, :rdata, :srid, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "bid": target_batch,
                "rnum": row_idx,
                "skey": str(l_key),
                "rhash": payload_hash,
                "rdata": payload_json,
                "srid": sr_id,
                "now": now_iso,
            },
        )

        migrated_keys[l_key] = {
            "source_record_id": sr_id,
            "entity_type": mapped_pool,
            "source_system": l_sys,
        }

    # Update import_batches metrics
    for b_id, counts in batch_counts.items():
        conn.execute(
            text(
                "UPDATE import_batches SET "
                "total_rows_received = :recv, total_rows_valid = :valid, "
                "total_rows_quarantined = :quar, total_rows_rejected = :rej "
                "WHERE id = :id"
            ),
            {"id": b_id, "recv": counts["recv"], "valid": counts["valid"], "quar": counts["quar"], "rej": counts["rej"]},
        )

    # -------------------------------------------------------------
    # 6. MIGRATE LEGACY CANDIDATE PAIRS
    # -------------------------------------------------------------
    has_legacy_pairs = False
    try:
        conn.execute(text("SELECT 1 FROM legacy_candidate_pairs LIMIT 1"))
        has_legacy_pairs = True
    except Exception:
        has_legacy_pairs = False

    legacy_pairs = []
    if has_legacy_pairs:
        legacy_pairs = conn.execute(
            text("SELECT id, left_source_key, right_source_key, similarity_score, reasons FROM legacy_candidate_pairs")
        ).fetchall()

    account_pairs_migrated = 0
    contact_pairs_migrated = 0

    for p in legacy_pairs:
        p_id, l_key, r_key, score, reasons = p

        l_cnt = key_counts.get(l_key, 0)
        r_cnt = key_counts.get(r_key, 0)

        # Precedence 1: Dangling Key
        if l_cnt == 0 or r_cnt == 0:
            continue

        # Precedence 2: Ambiguous Endpoint
        if l_cnt > 1 or r_cnt > 1:
            continue

        # Precedence 3: Quarantined Endpoint
        if l_key not in migrated_keys or r_key not in migrated_keys:
            continue

        l_info = migrated_keys[l_key]
        r_info = migrated_keys[r_key]

        # Precedence 4: Cross-Pool Mismatch
        if l_info["entity_type"] != r_info["entity_type"]:
            continue

        # Precedence 5: Valid Migrated Pair
        pool = l_info["entity_type"]
        assigned_run_id = ACCOUNT_RUN_ID if pool == "ACCOUNT" else CONTACT_RUN_ID

        # Canonical ordering: left_id < right_id
        l_rec_id = l_info["source_record_id"]
        r_rec_id = r_info["source_record_id"]
        left_id = min(l_rec_id, r_rec_id)
        right_id = max(l_rec_id, r_rec_id)

        clean_score = float(score) if score is not None else 85.0
        clean_score = max(0.0, min(100.0, clean_score))
        tier = "POTENTIAL_DUPLICATE" if clean_score >= 80.0 else "REVIEW"

        cand_pair_id = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO candidate_pairs ("
                "id, matching_run_id, left_source_record_id, right_source_record_id, entity_type, "
                "total_score, decision_tier, proposed_category, legacy_pair_id, legacy_reasons_raw, "
                "is_migrated_legacy, created_at"
                ") VALUES ("
                ":id, :mid, :lid, :rid, :pool, :score, :tier, 'MERGE_CANDIDATE', :lpid, :reasons, 1, :now"
                ")"
            ),
            {
                "id": cand_pair_id,
                "mid": assigned_run_id,
                "lid": left_id,
                "rid": right_id,
                "pool": pool,
                "score": clean_score,
                "tier": tier,
                "lpid": p_id,
                "reasons": str(reasons) if reasons else None,
                "now": now_iso,
            },
        )

        # Insert legacy evidence
        conn.execute(
            text(
                "INSERT INTO candidate_pair_evidence ("
                "id, candidate_pair_id, rule_name, field_name, similarity_score, "
                "evidence_direction, evidence_weight, is_legacy_evidence, provenance, created_at"
                ") VALUES ("
                ":id, :cpid, 'LEGACY_HEURISTIC', 'legacy_reasons', NULL, NULL, NULL, 1, 'LEGACY_MIGRATION', :now"
                ")"
            ),
            {"id": str(uuid.uuid4()), "cpid": cand_pair_id, "now": now_iso},
        )

        if pool == "ACCOUNT":
            account_pairs_migrated += 1
        else:
            contact_pairs_migrated += 1

    # -------------------------------------------------------------
    # 7. FINALIZE MATCHING RUNS (COMPLETED state)
    # -------------------------------------------------------------
    conn.execute(
        text("UPDATE matching_runs SET total_candidates = :cnt, status = 'COMPLETED', completed_at = :now WHERE id = :id"),
        {"cnt": account_pairs_migrated, "now": now_iso, "id": ACCOUNT_RUN_ID},
    )
    conn.execute(
        text("UPDATE matching_runs SET total_candidates = :cnt, status = 'COMPLETED', completed_at = :now WHERE id = :id"),
        {"cnt": contact_pairs_migrated, "now": now_iso, "id": CONTACT_RUN_ID},
    )

    # -------------------------------------------------------------
    # 8. MIGRATE LEGACY AUDIT LOGS
    # -------------------------------------------------------------
    has_legacy_audit = False
    try:
        conn.execute(text("SELECT 1 FROM legacy_audit_logs LIMIT 1"))
        has_legacy_audit = True
    except Exception:
        has_legacy_audit = False

    if has_legacy_audit:
        legacy_audits = conn.execute(
            text("SELECT id, action, actor, role, target_pair, reason, created_at FROM legacy_audit_logs")
        ).fetchall()
        for a in legacy_audits:
            a_id, act, actor, role, target, reason, a_created = a
            raw_str = f"{a_id}|{act}|{actor}|{role}|{target}|{reason}|{a_created}"
            evt_hash = hashlib.sha256(raw_str.encode("utf-8")).hexdigest()
            payload = {
                "legacy_audit_id": a_id,
                "legacy_role": role,
                "legacy_reason": reason,
                "original_target": str(target),
            }
            clean_action = "UPDATE"
            if act in ("CREATE", "UPDATE", "DELETE", "PROPOSE", "APPROVE", "REJECT", "SPLIT", "MERGE", "EXPORT", "LOGIN"):
                clean_action = act

            conn.execute(
                text(
                    "INSERT INTO audit_events ("
                    "id, event_type, actor_id, actor_username, target_entity_type, target_entity_id, "
                    "action, details_payload, previous_event_hash, event_hash, is_migrated_legacy, "
                    "hash_generated_at_migration, created_at"
                    ") VALUES ("
                    ":id, 'LEGACY_AUDIT', NULL, :actor, 'CANDIDATE_PAIR', :target, :action, :payload, "
                    "NULL, :hash, 1, 1, :created"
                    ")"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "actor": actor or "system_legacy",
                    "target": str(target) if target else "UNKNOWN",
                    "action": clean_action,
                    "payload": json.dumps(payload),
                    "hash": evt_hash,
                    "created": str(a_created) if a_created else now_iso,
                },
            )

    # -------------------------------------------------------------
    # 9. INTEGRITY ASSERTIONS CHECK
    # -------------------------------------------------------------
    # Assertion A: All migrated pairs have existing left and right records
    mismatch_query = text(
        "SELECT cp.id FROM candidate_pairs cp "
        "LEFT JOIN source_records sl ON cp.left_source_record_id = sl.id "
        "LEFT JOIN source_records sr ON cp.right_source_record_id = sr.id "
        "WHERE cp.is_migrated_legacy = 1 AND (sl.id IS NULL OR sr.id IS NULL)"
    )
    mismatches = conn.execute(mismatch_query).fetchall()
    if mismatches:
        raise RuntimeError(f"Assertion A Failed: {len(mismatches)} migrated candidate pairs lack valid endpoints!")

    # Assertion B: Left and right records match candidate pair entity pool
    pool_mismatch_query = text(
        "SELECT cp.id FROM candidate_pairs cp "
        "JOIN source_records sl ON cp.left_source_record_id = sl.id "
        "JOIN source_records sr ON cp.right_source_record_id = sr.id "
        "WHERE cp.is_migrated_legacy = 1 AND (cp.entity_type != sl.entity_type OR cp.entity_type != sr.entity_type)"
    )
    pool_mismatches = conn.execute(pool_mismatch_query).fetchall()
    if pool_mismatches:
        raise RuntimeError(f"Assertion B Failed: {len(pool_mismatches)} candidate pairs breach entity pool boundaries!")

    # Assertion C: Canonical ordering left < right
    order_mismatch_query = text(
        "SELECT id FROM candidate_pairs WHERE left_source_record_id >= right_source_record_id"
    )
    order_mismatches = conn.execute(order_mismatch_query).fetchall()
    if order_mismatches:
        raise RuntimeError(f"Assertion C Failed: {len(order_mismatches)} candidate pairs violate left < right ordering!")

    # Assertion D: Conservation of records in batches
    for b_id, counts in batch_counts.items():
        if counts["recv"] != (counts["valid"] + counts["quar"] + counts["rej"]):
            raise RuntimeError(f"Assertion D Failed: Conservation of records violated in batch {b_id}!")

    logger.info("Migration 0008 successfully applied with full reconciliation and conservation of records.")

def downgrade() -> None:
    raise RuntimeError(
        "Migration 0008 is STRICTLY IRREVERSIBLE: legacy data has been reconciled into immutable target tables."
    )
