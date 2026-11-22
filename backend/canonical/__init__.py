"""Canonical Entity Management & Three-File Output Pipeline Package.

Milestone: P2.5 - Canonical Entity Management & Golden Record Consolidation
Package: backend.canonical
"""

from backend.canonical.constants import (
    ACCOUNT_CROSSWALK_HEADERS,
    CONTACT_ACCOUNT_MAPPING_HEADERS,
    CONTACT_CROSSWALK_HEADERS,
    CanonicalStatus,
    ContactAccountResolutionStatus,
    GoldenRecordStrategy,
    MembershipStatus,
    ProvenanceTypeEnum,
    RelationshipTypeEnum,
)
from backend.canonical.intake_service import (
    BatchIngestionReport,
    IntakeService,
    RowValidationResult,
)
from backend.canonical.matching_pipeline_service import (
    CanonicalMatchingPipelineService,
    FullPipelineMatchingReport,
    StepMatchingSummary,
    build_source_record_input,
)
from backend.canonical.activation_service import (
    ActivationResult,
    CanonicalActivationService,
    SingletonActivationSummary,
)
from backend.canonical.contact_account_resolver import (
    AccountEntityProfile,
    ContactAccountResolver,
    ContactResolutionResult,
    ResolutionCandidate,
)
from backend.canonical.golden_record_service import (
    FieldConsolidationPolicy,
    GoldenRecordService,
    GoldenRecordSummary,
)
from backend.canonical.export_service import (
    CanonicalExportService,
    CompleteReconciliationReport,
    ExportFileResult,
    ThreeFileOutputReport,
)

__all__ = [
    # Constants & Enums
    "CanonicalStatus",
    "MembershipStatus",
    "RelationshipTypeEnum",
    "ContactAccountResolutionStatus",
    "GoldenRecordStrategy",
    "ProvenanceTypeEnum",
    "ACCOUNT_CROSSWALK_HEADERS",
    "CONTACT_CROSSWALK_HEADERS",
    "CONTACT_ACCOUNT_MAPPING_HEADERS",
    # Services
    "IntakeService",
    "RowValidationResult",
    "BatchIngestionReport",
    "CanonicalMatchingPipelineService",
    "FullPipelineMatchingReport",
    "StepMatchingSummary",
    "build_source_record_input",
    "CanonicalActivationService",
    "ActivationResult",
    "SingletonActivationSummary",
    "ContactAccountResolver",
    "ContactResolutionResult",
    "ResolutionCandidate",
    "AccountEntityProfile",
    "GoldenRecordService",
    "GoldenRecordSummary",
    "FieldConsolidationPolicy",
    "CanonicalExportService",
    "ExportFileResult",
    "CompleteReconciliationReport",
    "ThreeFileOutputReport",
]
