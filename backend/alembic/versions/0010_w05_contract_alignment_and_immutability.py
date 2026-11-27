"""W05 Contract Alignment & Immutability Triggers

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27 13:40:00.000000

Aligns database schema with W04_Data_API_Contract_v0.2, W05_Contract_Review_Form_v0.1,
and full SongNhat RFP (DAT 01-08, MAT 01-08, REV 01-08, SEC 01-08, Annex C):
1. source_records: entity_level, access_label, eligibility_status (S-03, S-07, D-10, MAT 02).
2. source_identifiers: verification_status, valid_from, valid_to (DAT 06, Annex C).
3. candidate_pairs: version, same_entity_blocked, weak_evidence_only, nullable total_score (S-09, S-11).
4. candidate_pair_evidence: method, sharing, blocks_same_entity, sufficient_alone, explanation, explanation_source (S-10, CH-02, CH-03).
5. review_decisions: subject, is_active, is_latest, evidence_snapshot, nullable approved_by/approved_at for W05 proposals (S-12, D-07, D-08, REV 01, REV 03).
6. entity_relationships: source_record_id endpoints & affiliation_id (S-08, DB-7).
7. canonical_entities: redirect_to_canonical_id, retired_at, retirement_reason (REV 05).
8. Enforces DB-level SQL Triggers for raw record immutability & append-only logs (CL-03, D-02, D-06, DB-4).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType, ISOUtcDateTime


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. source_records: entity_level, access_label, eligibility_status
    with op.batch_alter_table("source_records") as batch_op:
        batch_op.add_column(sa.Column("entity_level", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("access_label", sa.String(100), nullable=False, server_default="internal_sales"))
        batch_op.add_column(sa.Column("eligibility_status", sa.String(50), nullable=False, server_default="eligible"))
        batch_op.create_index("ix_source_records_entity_level", ["entity_level"])
        batch_op.create_index("ix_source_records_access_label", ["access_label"])
        batch_op.create_index("ix_source_records_eligibility_status", ["eligibility_status"])
        batch_op.create_check_constraint("chk_source_rec_eligibility", "eligibility_status IN ('eligible', 'held_unknown_type', 'unscorable')")

    # 2. source_identifiers: verification_status, valid_from, valid_to (DAT 06, Annex C)
    with op.batch_alter_table("source_identifiers") as batch_op:
        batch_op.add_column(sa.Column("verification_status", sa.String(50), nullable=True))
        batch_op.add_column(sa.Column("valid_from", ISOUtcDateTime(), nullable=True))
        batch_op.add_column(sa.Column("valid_to", ISOUtcDateTime(), nullable=True))
        batch_op.create_check_constraint("chk_ident_temporal_validity", "valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from")

    # 3. candidate_pairs: version, same_entity_blocked, weak_evidence_only, nullable total_score
    with op.batch_alter_table("candidate_pairs") as batch_op:
        batch_op.alter_column("total_score", existing_type=sa.Float(), nullable=True)
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("same_entity_blocked", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
        batch_op.add_column(sa.Column("weak_evidence_only", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))

    # 4. candidate_pair_evidence: method, sharing, blocks_same_entity, sufficient_alone, explanation, explanation_source
    op.add_column("candidate_pair_evidence", sa.Column("method", sa.String(50), nullable=True))
    op.add_column("candidate_pair_evidence", sa.Column("sharing", sa.String(50), nullable=True))
    op.add_column("candidate_pair_evidence", sa.Column("blocks_same_entity", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
    op.add_column("candidate_pair_evidence", sa.Column("sufficient_alone", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
    op.add_column("candidate_pair_evidence", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("candidate_pair_evidence", sa.Column("explanation_source", sa.String(50), nullable=True))

    # 5. review_decisions: subject, is_active, is_latest, evidence_snapshot, nullable approved_by/approved_at
    with op.batch_alter_table("review_decisions") as batch_op:
        batch_op.drop_constraint("chk_no_self_approval", type_="check")
        batch_op.drop_constraint("chk_decision_status", type_="check")
        batch_op.alter_column("approved_by", existing_type=GUIDType(), nullable=True)
        batch_op.alter_column("approved_at", existing_type=ISOUtcDateTime(), nullable=True)
        batch_op.add_column(sa.Column("subject", sa.String(50), nullable=False, server_default="entity_identity"))
        batch_op.add_column(sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
        batch_op.add_column(sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("1" if dialect == "sqlite" else "true")))
        batch_op.add_column(sa.Column("evidence_snapshot", sa.JSON(), nullable=True))
        batch_op.create_check_constraint("chk_no_self_approval", "approved_by IS NULL OR proposed_by <> approved_by")
        batch_op.create_check_constraint("chk_decision_status", "status IN ('PENDING', 'PROPOSED', 'APPROVED', 'REJECTED', 'SUPERSEDED')")
        batch_op.create_check_constraint("chk_approved_requires_approver", "status <> 'APPROVED' OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)")

    # 6. entity_relationships: nullable canonical IDs + source_record_id endpoints + affiliation_id
    with op.batch_alter_table("entity_relationships") as batch_op:
        batch_op.alter_column("from_canonical_id", existing_type=GUIDType(), nullable=True)
        batch_op.alter_column("to_canonical_id", existing_type=GUIDType(), nullable=True)
        batch_op.add_column(sa.Column("from_source_record_id", GUIDType(), nullable=True))
        batch_op.add_column(sa.Column("to_source_record_id", GUIDType(), nullable=True))
        batch_op.add_column(sa.Column("affiliation_id", sa.String(100), nullable=True))
        batch_op.create_foreign_key("fk_rel_from_source_rec", "source_records", ["from_source_record_id"], ["id"], ondelete="CASCADE")
        batch_op.create_foreign_key("fk_rel_to_source_rec", "source_records", ["to_source_record_id"], ["id"], ondelete="CASCADE")
        batch_op.create_index("ix_entity_relationships_from_source_record_id", ["from_source_record_id"])
        batch_op.create_index("ix_entity_relationships_to_source_record_id", ["to_source_record_id"])

    # 7. canonical_entities: redirect_to_canonical_id, retired_at, retirement_reason (REV 05)
    with op.batch_alter_table("canonical_entities") as batch_op:
        batch_op.drop_constraint("chk_canonical_status", type_="check")
        batch_op.add_column(sa.Column("redirect_to_canonical_id", GUIDType(), nullable=True))
        batch_op.add_column(sa.Column("retired_at", ISOUtcDateTime(), nullable=True))
        batch_op.add_column(sa.Column("retirement_reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_canonical_redirect", "canonical_entities", ["redirect_to_canonical_id"], ["id"], ondelete="SET NULL")
        batch_op.create_index("ix_canonical_entities_redirect_to_canonical_id", ["redirect_to_canonical_id"])
        batch_op.create_check_constraint("chk_canonical_status", "status IN ('ACTIVE', 'MERGED', 'SPLIT', 'ARCHIVED', 'RETIRED')")

    # 8. Immutability & Append-Only Triggers (CL-03, D-02, D-06, DB-4)
    if dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_source_records_immutable_raw
            BEFORE UPDATE ON source_records
            FOR EACH ROW
            WHEN NEW.record_payload IS NOT OLD.record_payload
            BEGIN
                SELECT RAISE(ABORT, 'IMMUTABILITY_VIOLATION: raw record_payload cannot be updated');
            END;
        """)
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_review_decisions_no_update
            BEFORE UPDATE ON review_decisions
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: review_decisions cannot be updated');
            END;
        """)
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_review_decisions_no_delete
            BEFORE DELETE ON review_decisions
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: review_decisions cannot be deleted');
            END;
        """)
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_update
            BEFORE UPDATE ON audit_events
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: audit_events cannot be updated');
            END;
        """)
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_audit_events_no_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'APPEND_ONLY_VIOLATION: audit_events cannot be deleted');
            END;
        """)
    elif dialect == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION fn_prevent_raw_update() RETURNS TRIGGER AS $$
            BEGIN
                IF NEW.record_payload IS DISTINCT FROM OLD.record_payload THEN
                    RAISE EXCEPTION 'IMMUTABILITY_VIOLATION: raw record_payload cannot be updated';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_source_records_immutable_raw
            BEFORE UPDATE ON source_records
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_raw_update();

            CREATE OR REPLACE FUNCTION fn_prevent_append_only_mutation() RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'APPEND_ONLY_VIOLATION: % table is strictly append-only', TG_TABLE_NAME;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_review_decisions_no_update
            BEFORE UPDATE OR DELETE ON review_decisions
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_append_only_mutation();

            CREATE TRIGGER trg_audit_events_no_update
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION fn_prevent_append_only_mutation();
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_delete;")
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_review_decisions_no_delete;")
        op.execute("DROP TRIGGER IF EXISTS trg_review_decisions_no_update;")
        op.execute("DROP TRIGGER IF EXISTS trg_source_records_immutable_raw;")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_audit_events_no_update ON audit_events;")
        op.execute("DROP TRIGGER IF EXISTS trg_review_decisions_no_update ON review_decisions;")
        op.execute("DROP TRIGGER IF EXISTS trg_source_records_immutable_raw ON source_records;")
        op.execute("DROP FUNCTION IF EXISTS fn_prevent_append_only_mutation();")
        op.execute("DROP FUNCTION IF EXISTS fn_prevent_raw_update();")

    with op.batch_alter_table("canonical_entities") as batch_op:
        batch_op.drop_constraint("chk_canonical_status", type_="check")
        batch_op.drop_index("ix_canonical_entities_redirect_to_canonical_id")
        batch_op.drop_constraint("fk_canonical_redirect", type_="foreignkey")
        batch_op.drop_column("retirement_reason")
        batch_op.drop_column("retired_at")
        batch_op.drop_column("redirect_to_canonical_id")
        batch_op.create_check_constraint("chk_canonical_status", "status IN ('ACTIVE', 'MERGED', 'SPLIT', 'ARCHIVED')")

    with op.batch_alter_table("entity_relationships") as batch_op:
        batch_op.drop_index("ix_entity_relationships_to_source_record_id")
        batch_op.drop_index("ix_entity_relationships_from_source_record_id")
        batch_op.drop_constraint("fk_rel_to_source_rec", type_="foreignkey")
        batch_op.drop_constraint("fk_rel_from_source_rec", type_="foreignkey")
        batch_op.drop_column("affiliation_id")
        batch_op.drop_column("to_source_record_id")
        batch_op.drop_column("from_source_record_id")
        batch_op.alter_column("to_canonical_id", existing_type=GUIDType(), nullable=False)
        batch_op.alter_column("from_canonical_id", existing_type=GUIDType(), nullable=False)

    with op.batch_alter_table("review_decisions") as batch_op:
        batch_op.drop_constraint("chk_approved_requires_approver", type_="check")
        batch_op.drop_constraint("chk_decision_status", type_="check")
        batch_op.drop_constraint("chk_no_self_approval", type_="check")
        batch_op.drop_column("evidence_snapshot")
        batch_op.drop_column("is_latest")
        batch_op.drop_column("is_active")
        batch_op.drop_column("subject")
        batch_op.alter_column("approved_at", existing_type=ISOUtcDateTime(), nullable=False)
        batch_op.alter_column("approved_by", existing_type=GUIDType(), nullable=False)
        batch_op.create_check_constraint("chk_no_self_approval", "proposed_by <> approved_by")
        batch_op.create_check_constraint("chk_decision_status", "status IN ('PENDING', 'APPROVED', 'REJECTED', 'SUPERSEDED')")

    op.drop_column("candidate_pair_evidence", "explanation_source")
    op.drop_column("candidate_pair_evidence", "explanation")
    op.drop_column("candidate_pair_evidence", "sufficient_alone")
    op.drop_column("candidate_pair_evidence", "blocks_same_entity")
    op.drop_column("candidate_pair_evidence", "sharing")
    op.drop_column("candidate_pair_evidence", "method")

    with op.batch_alter_table("candidate_pairs") as batch_op:
        batch_op.drop_column("weak_evidence_only")
        batch_op.drop_column("same_entity_blocked")
        batch_op.drop_column("version")
        batch_op.alter_column("total_score", existing_type=sa.Float(), nullable=False)

    with op.batch_alter_table("source_identifiers") as batch_op:
        batch_op.drop_constraint("chk_ident_temporal_validity", type_="check")
        batch_op.drop_column("valid_to")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("verification_status")

    with op.batch_alter_table("source_records") as batch_op:
        batch_op.drop_constraint("chk_source_rec_eligibility", type_="check")
        batch_op.drop_index("ix_source_records_eligibility_status")
        batch_op.drop_index("ix_source_records_access_label")
        batch_op.drop_index("ix_source_records_entity_level")
        batch_op.drop_column("eligibility_status")
        batch_op.drop_column("access_label")
        batch_op.drop_column("entity_level")
