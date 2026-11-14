"""Constants, Enums and Export File Contracts for Milestone P2.5.

Module: backend.canonical.constants
Updated to comply with: 2 CSV Deliverables + 1 Comprehensive PDF Report.
"""

from enum import Enum
from typing import List


class CanonicalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MERGED = "MERGED"
    SPLIT = "SPLIT"
    ARCHIVED = "ARCHIVED"


class MembershipStatus(str, Enum):
    USABLE = "USABLE"
    HELD = "HELD"
    SUPERSEDED = "SUPERSEDED"
    RETRACTED = "RETRACTED"


class RelationshipTypeEnum(str, Enum):
    COMPANY_HAS_BRANCH = "COMPANY_HAS_BRANCH"
    BRANCH_HAS_SITE = "BRANCH_HAS_SITE"
    PERSON_WORKS_FOR_COMPANY = "PERSON_WORKS_FOR_COMPANY"
    PERSON_CONTACTS_BRANCH = "PERSON_CONTACTS_BRANCH"


class ContactAccountResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    MATCHED = "RESOLVED"  # Alias for backward compatibility
    UNRESOLVED = "UNRESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    CONFLICT = "CONFLICT"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    NO_AFFILIATION = "NO_AFFILIATION"


class MatchingScopeEnum(str, Enum):
    A_A = "A_A"
    B_B = "B_B"
    A_B = "A_B"
    C_C = "C_C"
    SINGLETON = "SINGLETON"


class GoldenRecordStrategy(str, Enum):
    SOURCE_PRIORITY = "SOURCE_PRIORITY"
    LATEST_VALID_VALUE = "LATEST_VALID_VALUE"
    VERIFIED_VALUE = "VERIFIED_VALUE"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    CONFLICT_REVIEW = "CONFLICT_REVIEW"


class ProvenanceTypeEnum(str, Enum):
    DIRECT_SOURCE = "DIRECT_SOURCE"
    STEWARD_OVERRIDE = "STEWARD_OVERRIDE"
    AGGREGATED_RULE = "AGGREGATED_RULE"


# =============================================================================
# MANDATORY DELIVERABLE CONTRACTS: EXACTLY 2 CSVs + 1 PDF
# =============================================================================

# FILE 1: `account_crosswalk_A_B.csv` (18 Headers)
ACCOUNT_CROSSWALK_A_B_HEADERS: List[str] = [
    "canonical_account_id",
    "source_system",
    "source_record_key",
    "source_record_version",
    "entity_type",
    "raw_account_name",
    "tax_code_raw",
    "phone_raw",
    "address_raw",
    "matching_scope",
    "matching_decision",
    "review_status",
    "approval_status",
    "evidence_reference",
    "canonical_membership_id",
    "valid_from",
    "valid_to",
    "provenance",
]

# Legacy alias for backward compatibility
ACCOUNT_CROSSWALK_HEADERS = ACCOUNT_CROSSWALK_A_B_HEADERS

# FILE 2: `contact_account_mapping.csv` (21 Headers)
CONTACT_ACCOUNT_MAPPING_HEADERS: List[str] = [
    "canonical_contact_id",
    "source_contact_system",
    "source_contact_key",
    "source_contact_version",
    "raw_contact_name",
    "contact_matching_scope",
    "contact_matching_decision",
    "contact_review_status",
    "canonical_account_id",
    "account_source_system",
    "account_source_key",
    "relationship_type",
    "raw_company_affiliation",
    "relationship_evidence",
    "relationship_resolution_status",
    "approval_status",
    "approver",
    "decision_time",
    "valid_from",
    "valid_to",
    "provenance",
]

# Legacy alias
CONTACT_CROSSWALK_HEADERS: List[str] = [
    "canonical_contact_id",
    "source_system",
    "source_key",
    "source_record_id",
    "source_record_version_id",
    "contact_name_raw",
    "phone_raw",
    "email_raw",
    "membership_status",
    "decision_id",
    "approval_status",
    "valid_from",
    "valid_to",
    "provenance_reference",
]
