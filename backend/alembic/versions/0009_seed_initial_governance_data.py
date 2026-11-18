"""Seed initial governance and access control data

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-14

"""
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import text

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INITIAL_ROLES = [
    ("DATA_STEWARD", "Data Steward", "Responsible for record ingestion, feature review, and proposing merge/split decisions"),
    ("APPROVER", "Approver", "Responsible for adjudicating proposed decisions and Maker-Checker sign-off"),
    ("ADMINISTRATOR", "Administrator", "System administrator with full operational and governance control"),
    ("AUDITOR", "Auditor", "Read-only compliance auditor with access to deletion ledger and hash chains"),
]

INITIAL_PERMISSIONS = [
    ("RECORD_VIEW", "intake", "View raw and normalized records"),
    ("RECORD_EDIT", "intake", "Edit source record attributes"),
    ("TASK_REVIEW", "review", "View and process review tasks"),
    ("DECISION_PROPOSE", "review", "Propose merge, split, or hold decisions"),
    ("DECISION_APPROVE", "review", "Approve or reject proposed decisions (Checker role)"),
    ("CANONICAL_MERGE", "canonical", "Execute canonical entity merge"),
    ("CANONICAL_SPLIT", "canonical", "Execute canonical entity split"),
    ("EXPORT_GENERATE", "export", "Trigger downstream export jobs"),
    ("AUDIT_VIEW", "governance", "View audit trail and verify integrity hashes"),
    ("ADMIN_ALL", "admin", "Full administrative privileges"),
]

ROLE_PERMISSION_MAP = {
    "DATA_STEWARD": ["RECORD_VIEW", "TASK_REVIEW", "DECISION_PROPOSE"],
    "APPROVER": ["RECORD_VIEW", "TASK_REVIEW", "DECISION_APPROVE", "CANONICAL_MERGE", "CANONICAL_SPLIT"],
    "AUDITOR": ["RECORD_VIEW", "AUDIT_VIEW"],
    "ADMINISTRATOR": [
        "RECORD_VIEW", "RECORD_EDIT", "TASK_REVIEW", "DECISION_PROPOSE",
        "DECISION_APPROVE", "CANONICAL_MERGE", "CANONICAL_SPLIT",
        "EXPORT_GENERATE", "AUDIT_VIEW", "ADMIN_ALL"
    ],
}

INITIAL_RETENTION_POLICIES = [
    ("AUDIT_LOG_RETENTION", "audit_events", None, 3650, "ARCHIVE"),
    ("SOURCE_RECORDS_RETENTION", "source_records", "ACCOUNT", 2555, "SOFT_DELETE"),
    ("SOURCE_RECORDS_CONTACT_RETENTION", "source_records", "CONTACT", 1825, "SOFT_DELETE"),
    ("CANDIDATE_PAIRS_RETENTION", "candidate_pairs", None, 1095, "HARD_DELETE"),
]

def upgrade() -> None:
    conn = op.get_bind()
    now_iso = datetime.now(timezone.utc).isoformat()

    role_ids = {}
    for role_code, role_name, desc in INITIAL_ROLES:
        exists = conn.execute(text("SELECT id FROM roles WHERE role_code = :code"), {"code": role_code}).fetchone()
        if exists:
            role_ids[role_code] = str(exists[0])
        else:
            r_id = str(uuid.uuid4())
            conn.execute(
                text("INSERT INTO roles (id, role_code, role_name, description, created_at) "
                     "VALUES (:id, :code, :name, :desc, :now)"),
                {"id": r_id, "code": role_code, "name": role_name, "desc": desc, "now": now_iso},
            )
            role_ids[role_code] = r_id

    perm_ids = {}
    for perm_code, mod, desc in INITIAL_PERMISSIONS:
        exists = conn.execute(text("SELECT id FROM permissions WHERE permission_code = :code"), {"code": perm_code}).fetchone()
        if exists:
            perm_ids[perm_code] = str(exists[0])
        else:
            p_id = str(uuid.uuid4())
            conn.execute(
                text("INSERT INTO permissions (id, permission_code, module, description, created_at) "
                     "VALUES (:id, :code, :mod, :desc, :now)"),
                {"id": p_id, "code": perm_code, "mod": mod, "desc": desc, "now": now_iso},
            )
            perm_ids[perm_code] = p_id

    for role_code, perms in ROLE_PERMISSION_MAP.items():
        r_id = role_ids[role_code]
        for p_code in perms:
            p_id = perm_ids[p_code]
            exists = conn.execute(
                text("SELECT role_id FROM role_permissions WHERE role_id = :rid AND permission_id = :pid"),
                {"rid": r_id, "pid": p_id},
            ).fetchone()
            if not exists:
                conn.execute(
                    text("INSERT INTO role_permissions (role_id, permission_id, granted_at) "
                         "VALUES (:rid, :pid, :now)"),
                    {"rid": r_id, "pid": p_id, "now": now_iso},
                )

    for pol_name, target_tbl, ent_type, days, action in INITIAL_RETENTION_POLICIES:
        exists = conn.execute(
            text("SELECT id FROM retention_policies WHERE target_table = :tbl AND (entity_type = :etype OR (entity_type IS NULL AND :etype IS NULL))"),
            {"tbl": target_tbl, "etype": ent_type},
        ).fetchone()
        if not exists:
            conn.execute(
                text("INSERT INTO retention_policies (id, policy_name, target_table, entity_type, retention_days, action_on_expiry, is_active, created_at) "
                     "VALUES (:id, :name, :tbl, :etype, :days, :action, 1, :now)"),
                {"id": str(uuid.uuid4()), "name": pol_name, "tbl": target_tbl, "etype": ent_type, "days": days, "action": action, "now": now_iso},
            )

def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("DELETE FROM role_permissions"))
    conn.execute(text("DELETE FROM permissions"))
    conn.execute(text("DELETE FROM roles"))
    conn.execute(text("DELETE FROM retention_policies"))
