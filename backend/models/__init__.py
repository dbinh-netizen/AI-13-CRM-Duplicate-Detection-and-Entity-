from backend.models.base import Base, GUIDType, ISOUtcDateTime

# Domain 1: User & Access Control (5 tables)
from backend.models.access_control import (
    User,
    Role,
    Permission,
    UserRole,
    RolePermission,
)

# Domain 2: Source & Intake Management (8 tables)
from backend.models.intake import (
    SourceSystem,
    ImportBatch,
    SourceRecord,
    SourceRecordVersion,
    BatchRowResult,
    SourceIdentifier,
    MatchingRun,
    RunSource,
)

# Domain 3: Normalization & Matching (5 tables)
from backend.models.matching import (
    NormalizationPolicy,
    NormalizedFeature,
    CandidatePair,
    CandidateBlockingPath,
    CandidatePairEvidence,
)

# Domain 4: Cluster & Human Review (5 tables)
from backend.models.review import (
    CandidateCluster,
    CandidateClusterMember,
    ReviewTask,
    ReviewDecision,
    PairDecisionConstraint,
)

# Domain 5: Canonical Resolution & Hierarchy (5 tables)
from backend.models.canonical import (
    CanonicalEntity,
    CanonicalMembership,
    CanonicalField,
    CanonicalFieldProvenance,
    EntityRelationship,
)

# Domain 6 & 7: Governance, Audit & Export (5 tables: 3 Domain 6 + 2 Domain 7)
from backend.models.governance import (
    AuditEvent,
    RetentionPolicy,
    DeletionLedger,
    ExportJob,
    ExportManifestItem,
)

# Legacy Staging Tables (3 tables - Staging Layer)
from backend.models.legacy import (
    LegacySourceRecord,
    LegacyCandidatePair,
    LegacyAuditLog,
)

DOMAIN_1_ACCESS_CONTROL = [
    "users", "roles", "permissions", "user_roles", "role_permissions"
]

DOMAIN_2_INTAKE_SOURCE = [
    "source_systems", "import_batches", "source_records", "source_record_versions",
    "batch_row_results", "source_identifiers", "matching_runs", "run_sources"
]

DOMAIN_3_NORMALIZATION_MATCHING = [
    "normalization_policies", "normalized_features", "candidate_pairs",
    "candidate_blocking_paths", "candidate_pair_evidence"
]

DOMAIN_4_REVIEW_WORKFLOW = [
    "candidate_clusters", "candidate_cluster_members", "review_tasks",
    "review_decisions", "pair_decision_constraints"
]

DOMAIN_5_CANONICAL_RESOLUTION = [
    "canonical_entities", "canonical_memberships", "canonical_fields",
    "canonical_field_provenance", "entity_relationships"
]

DOMAIN_6_GOVERNANCE_AUDIT = [
    "audit_events", "retention_policies", "deletion_ledger"
]

DOMAIN_7_EXPORT_DOWNSTREAM = [
    "export_jobs", "export_manifest_items"
]

TARGET_TABLES = (
    DOMAIN_1_ACCESS_CONTROL
    + DOMAIN_2_INTAKE_SOURCE
    + DOMAIN_3_NORMALIZATION_MATCHING
    + DOMAIN_4_REVIEW_WORKFLOW
    + DOMAIN_5_CANONICAL_RESOLUTION
    + DOMAIN_6_GOVERNANCE_AUDIT
    + DOMAIN_7_EXPORT_DOWNSTREAM
)

LEGACY_TABLES = [
    "legacy_source_records",
    "legacy_candidate_pairs",
    "legacy_audit_logs",
]

__all__ = [
    "Base", "GUIDType", "ISOUtcDateTime",
    # Domain 1
    "User", "Role", "Permission", "UserRole", "RolePermission",
    # Domain 2
    "SourceSystem", "ImportBatch", "SourceRecord", "SourceRecordVersion",
    "BatchRowResult", "SourceIdentifier", "MatchingRun", "RunSource",
    # Domain 3
    "NormalizationPolicy", "NormalizedFeature", "CandidatePair",
    "CandidateBlockingPath", "CandidatePairEvidence",
    # Domain 4
    "CandidateCluster", "CandidateClusterMember", "ReviewTask",
    "ReviewDecision", "PairDecisionConstraint",
    # Domain 5
    "CanonicalEntity", "CanonicalMembership", "CanonicalField",
    "CanonicalFieldProvenance", "EntityRelationship",
    # Domain 6 & 7
    "AuditEvent", "RetentionPolicy", "DeletionLedger", "ExportJob", "ExportManifestItem",
    # Legacy
    "LegacySourceRecord", "LegacyCandidatePair", "LegacyAuditLog",
    # Metadata collections
    "TARGET_TABLES", "LEGACY_TABLES",
    "DOMAIN_1_ACCESS_CONTROL", "DOMAIN_2_INTAKE_SOURCE",
    "DOMAIN_3_NORMALIZATION_MATCHING", "DOMAIN_4_REVIEW_WORKFLOW",
    "DOMAIN_5_CANONICAL_RESOLUTION", "DOMAIN_6_GOVERNANCE_AUDIT",
    "DOMAIN_7_EXPORT_DOWNSTREAM",
]
