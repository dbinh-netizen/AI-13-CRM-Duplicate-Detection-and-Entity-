"""W05 Contract Alignment & Immutability Triggers

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-27 13:40:00.000000

Aligns database schema with W04_Data_API_Contract_v0.2 & W05_Contract_Review_Form_v0.1:
1. Adds entity_level and access_label to source_records (S-03, D-10).
2. Adds version, same_entity_blocked, weak_evidence_only, nullable total_score to candidate_pairs (S-09, S-11).
3. Adds method, sharing, blocks_same_entity, sufficient_alone, explanation, explanation_source to candidate_pair_evidence (S-10, CH-02, CH-03).
4. Adds subject, is_active, is_latest, evidence_snapshot to review_decisions (S-12, D-07, D-08).
5. Supports source_record_id endpoints & affiliation_id on entity_relationships (S-08, DB-7).
6. Enforces DB-level SQL Triggers for raw record immutability & append-only logs (CL-03, D-02, D-06, DB-4).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from backend.models.base import GUIDType


# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # 1. source_records: entity_level, access_label
    op.add_column("source_records", sa.Column("entity_level", sa.String(50), nullable=True))
    op.add_column("source_records", sa.Column("access_label", sa.String(100), nullable=False, server_default="internal_sales"))
    op.create_index("ix_source_records_entity_level", "source_records", ["entity_level"])
    op.create_index("ix_source_records_access_label", "source_records", ["access_label"])

    # 2. candidate_pairs: version, same_entity_blocked, weak_evidence_only, nullable total_score
    with op.batch_alter_table("candidate_pairs") as batch_op:
        batch_op.alter_column("total_score", existing_type=sa.Float(), nullable=True)
        batch_op.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("same_entity_blocked", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
        batch_op.add_column(sa.Column("weak_evidence_only", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))

    # 3. candidate_pair_evidence: method, sharing, blocks_same_entity, sufficient_alone, explanation, explanation_source
    op.add_column("candidate_pair_evidence", sa.Column("method", sa.String(50), nullable=True))
    op.add_column("candidate_pair_evidence", sa.Column("sharing", sa.String(50), nullable=True))
    op.add_column("candidate_pair_evidence", sa.Column("blocks_same_entity", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
    op.add_column("candidate_pair_evidence", sa.Column("sufficient_alone", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
    op.add_column("candidate_pair_evidence", sa.Column("explanation", sa.Text(), nullable=True))
    op.add_column("candidate_pair_evidence", sa.Column("explanation_source", sa.String(50), nullable=True))

    # 4. review_decisions: subject, is_active, is_latest, evidence_snapshot
    op.add_column("review_decisions", sa.Column("subject", sa.String(50), nullable=False, server_default="entity_identity"))
    op.add_column("review_decisions", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("0" if dialect == "sqlite" else "false")))
    op.add_column("review_decisions", sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("1" if dialect == "sqlite" else "true")))
    op.add_column("review_decisions", sa.Column("evidence_snapshot", sa.JSON(), nullable=True))

    # 5. entity_relationships: nullable canonical IDs + source_record_id endpoints + affiliation_id
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

    # 6. Immutability & Append-Only Triggers (CL-03, D-02, D-06, DB-4)
    if dialect == "sqlite":
        # Protect source_records.record_payload from modification
        op.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_source_records_immutable_raw
            BEFORE UPDATE ON source_records
            FOR EACH ROW
            WHEN NEW.record_payload IS NOT OLD.record_payload
            BEGIN
                SELECT RAISE(ABORT, 'IMMUTABILITY_VIOLATION: raw record_payload cannot be updated');
            END;
        """)
        # Protect review_decisions from UPDATE / DELETE (append-only)
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
        # Protect audit_events from UPDATE / DELETE (append-only)
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

    op.drop_column("review_decisions", "evidence_snapshot")
    op.drop_column("review_decisions", "is_latest")
    op.drop_column("review_decisions", "is_active")
    op.drop_column("review_decisions", "subject")

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

    op.drop_index("ix_source_records_access_label", "source_records")
    op.drop_index("ix_source_records_entity_level", "source_records")
    op.drop_column("source_records", "access_label")
    op.drop_column("source_records", "entity_level")
