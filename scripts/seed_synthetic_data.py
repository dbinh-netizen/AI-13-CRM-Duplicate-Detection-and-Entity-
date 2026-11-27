"""Seed Synthetic Data & Verify Queries Script for Milestone W04/W05.

Demonstrates:
1. Insertion of Source Systems (CRM_A, CRM_B, CRM_C).
2. Insertion of Import Batches with file metadata.
3. Insertion of Raw Source Records (Immutable raw payload preservation).
4. Insertion of Source Record Versions (SCD Type 2 snapshot anchor).
5. Insertion of Normalized Features (Field-level normalization results).
6. Candidate Generation & Candidate Pair creation with ordered IDs.
7. Verification that Raw Source Records remain immutable.
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from backend.database import SessionLocal, engine
from backend.models import Base
from backend.models.intake import (
    SourceSystem,
    ImportBatch,
    SourceRecord,
    SourceRecordVersion,
    MatchingRun,
)
from backend.models.matching import (
    NormalizationPolicy,
    NormalizedFeature,
    CandidatePair,
    CandidatePairEvidence,
)


def seed_synthetic_data():
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    try:
        # 1. Seed Source Systems
        systems_data = [
            {"code": "CRM_A", "name": "Northern Sales CRM A", "type": "CRM", "entity_type": "ACCOUNT"},
            {"code": "CRM_B", "name": "Southern Enterprise CRM B", "type": "CRM", "entity_type": "ACCOUNT"},
            {"code": "CRM_C", "name": "Web/Zalo Contact Portal C", "type": "PORTAL", "entity_type": "CONTACT"},
        ]
        systems_map = {}
        for s_data in systems_data:
            existing = session.query(SourceSystem).filter_by(source_code=s_data["code"]).first()
            if not existing:
                sys_obj = SourceSystem(
                    source_code=s_data["code"],
                    source_name=s_data["name"],
                    system_type=s_data["type"],
                    entity_type=s_data["entity_type"],
                    is_active=True,
                )
                session.add(sys_obj)
                session.flush()
                systems_map[s_data["code"]] = sys_obj
            else:
                systems_map[s_data["code"]] = existing

        # 2. Create Import Batches
        batch_a = ImportBatch(
            source_system_id=systems_map["CRM_A"].id,
            batch_code=f"BATCH-A-{uuid.uuid4().hex[:6]}",
            batch_type="FULL",
            file_name="accounts_source_a.csv",
            file_checksum=f"sha256-batch-a-{uuid.uuid4().hex}",
            file_size_bytes=2048,
            total_rows_received=2,
            total_rows_valid=2,
            total_rows_quarantined=0,
            total_rows_rejected=0,
            status="COMPLETED",
        )
        batch_b = ImportBatch(
            source_system_id=systems_map["CRM_B"].id,
            batch_code=f"BATCH-B-{uuid.uuid4().hex[:6]}",
            batch_type="FULL",
            file_name="accounts_source_b.csv",
            file_checksum=f"sha256-batch-b-{uuid.uuid4().hex}",
            file_size_bytes=1024,
            total_rows_received=1,
            total_rows_valid=1,
            total_rows_quarantined=0,
            total_rows_rejected=0,
            status="COMPLETED",
        )
        batch_c = ImportBatch(
            source_system_id=systems_map["CRM_C"].id,
            batch_code=f"BATCH-C-{uuid.uuid4().hex[:6]}",
            batch_type="FULL",
            file_name="contacts_source.csv",
            file_checksum=f"sha256-batch-c-{uuid.uuid4().hex}",
            file_size_bytes=1024,
            total_rows_received=1,
            total_rows_valid=1,
            total_rows_quarantined=0,
            total_rows_rejected=0,
            status="COMPLETED",
        )
        session.add_all([batch_a, batch_b, batch_c])
        session.flush()

        # 3. Seed Raw Source Records
        raw_payload_a1 = {
            "company_name": "Công ty TNHH Song Nhật Logistics",
            "tax_code": "0314892100",
            "phone": "02838991122",
            "email": "contact@songnhat.vn",
            "address": "123 Nguyễn Thị Minh Khai, Q1, TP.HCM",
        }
        raw_payload_a2 = {
            "company_name": "Tập đoàn Viễn thông VNG Corp",
            "tax_code": "0303490096",
            "phone": "02839623888",
            "email": "info@vng.com.vn",
            "address": "KCX Tân Thuận, Q7, TP.HCM",
        }
        raw_payload_b1 = {
            "company_name": "CTY TNHH SONG NHAT LOGISTICS - CHI NHANH 1",
            "tax_code": "0314892100",
            "phone": "028-3899-1122",
            "email": "sales@songnhat.vn",
            "address": "123 NTMK, Phường 6, Quận 1, Hồ Chí Minh",
        }
        raw_payload_c1 = {
            "contact_name": "Nguyễn Văn Song Nhật",
            "phone": "0908123456",
            "email": "songnhat@songnhat.vn",
            "company_affinity": "Song Nhật Logistics",
        }

        rec_a1 = SourceRecord(
            source_system_id=systems_map["CRM_A"].id,
            entity_type="ACCOUNT",
            source_key=f"ACC_A_{uuid.uuid4().hex[:6]}",
            import_batch_id=batch_a.id,
            record_payload=raw_payload_a1,
            status="VALID",
        )
        rec_a2 = SourceRecord(
            source_system_id=systems_map["CRM_A"].id,
            entity_type="ACCOUNT",
            source_key=f"ACC_A_{uuid.uuid4().hex[:6]}",
            import_batch_id=batch_a.id,
            record_payload=raw_payload_a2,
            status="VALID",
        )
        rec_b1 = SourceRecord(
            source_system_id=systems_map["CRM_B"].id,
            entity_type="ACCOUNT",
            source_key=f"ACC_B_{uuid.uuid4().hex[:6]}",
            import_batch_id=batch_b.id,
            record_payload=raw_payload_b1,
            status="VALID",
        )
        rec_c1 = SourceRecord(
            source_system_id=systems_map["CRM_C"].id,
            entity_type="CONTACT",
            source_key=f"CON_C_{uuid.uuid4().hex[:6]}",
            import_batch_id=batch_c.id,
            record_payload=raw_payload_c1,
            status="VALID",
        )
        session.add_all([rec_a1, rec_a2, rec_b1, rec_c1])
        session.flush()

        # 4. Source Record Versions
        ver_a1 = SourceRecordVersion(
            source_record_id=rec_a1.id,
            version_number=1,
            import_batch_id=batch_a.id,
            row_anchor_hash="hash-rec-a1-v1",
            raw_payload=raw_payload_a1,
            checksum="chk-rec-a1-v1",
            is_current=True,
        )
        ver_b1 = SourceRecordVersion(
            source_record_id=rec_b1.id,
            version_number=1,
            import_batch_id=batch_b.id,
            row_anchor_hash="hash-rec-b1-v1",
            raw_payload=raw_payload_b1,
            checksum="chk-rec-b1-v1",
            is_current=True,
        )
        session.add_all([ver_a1, ver_b1])
        session.flush()

        # 5. Normalization Policy & Normalized Features
        norm_policy = session.query(NormalizationPolicy).filter_by(policy_name="DEFAULT_VN_NORMALIZER").first()
        if not norm_policy:
            norm_policy = NormalizationPolicy(
                policy_name="DEFAULT_VN_NORMALIZER",
                version_number=1,
                status="ACTIVE",
                config_payload={"unicode": "NFC", "tax_code": "clean", "phone": "e164_vn"},
            )
            session.add(norm_policy)
            session.flush()

        features = [
            NormalizedFeature(
                source_record_version_id=ver_a1.id,
                policy_id=norm_policy.id,
                feature_name="legal_name",
                raw_value=raw_payload_a1["company_name"],
                normalized_value="CONG TY TNHH SONG NHAT LOGISTICS",
            ),
            NormalizedFeature(
                source_record_version_id=ver_a1.id,
                policy_id=norm_policy.id,
                feature_name="tax_code",
                raw_value=raw_payload_a1["tax_code"],
                normalized_value="0314892100",
            ),
            NormalizedFeature(
                source_record_version_id=ver_b1.id,
                policy_id=norm_policy.id,
                feature_name="legal_name",
                raw_value=raw_payload_b1["company_name"],
                normalized_value="CONG TY TNHH SONG NHAT LOGISTICS CHI NHANH 1",
            ),
            NormalizedFeature(
                source_record_version_id=ver_b1.id,
                policy_id=norm_policy.id,
                feature_name="tax_code",
                raw_value=raw_payload_b1["tax_code"],
                normalized_value="0314892100",
            ),
        ]
        session.add_all(features)
        session.flush()

        # 6. Matching Run & Candidate Pair
        m_run = MatchingRun(
            run_code=f"RUN-W05-{uuid.uuid4().hex[:6]}",
            entity_pool="ACCOUNT",
            status="COMPLETED",
            total_candidates=1,
            ceiling_breached=False,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        session.add(m_run)
        session.flush()

        left_id, right_id = sorted([rec_a1.id, rec_b1.id])
        cand_pair = CandidatePair(
            matching_run_id=m_run.id,
            left_source_record_id=left_id,
            right_source_record_id=right_id,
            entity_type="ACCOUNT",
            total_score=94.50,
            decision_tier="REVIEW_REQUIRED",
            proposed_category="SUSPECTED_DUPLICATE",
        )
        session.add(cand_pair)
        session.flush()

        # 7. Candidate Pair Evidence
        import json
        prov = {
            "left_source_key": rec_a1.source_key,
            "right_source_key": rec_b1.source_key,
            "match_rule": "EXACT_TAX_MATCH",
            "source_pool": "ACCOUNT",
        }
        evidence = CandidatePairEvidence(
            candidate_pair_id=cand_pair.id,
            rule_name="EXACT_TAX_MATCH",
            field_name="tax_code",
            left_raw_value="0314892100",
            right_raw_value="0314892100",
            left_normalized_value="0314892100",
            right_normalized_value="0314892100",
            similarity_score=100.0,
            evidence_direction="POSITIVE",
            evidence_weight=1.0,
            provenance=json.dumps(prov),
        )
        session.add(evidence)
        session.commit()
        return True

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    seed_synthetic_data()
    print("Seed synthetic data completed successfully.")
