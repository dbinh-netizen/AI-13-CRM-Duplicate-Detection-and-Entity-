# DATABASE PHYSICAL & LOGICAL SCHEMA SPECIFICATION (33 TABLES)
## SongNhat CRM Duplicate Detection and Entity Resolution System
### Version: 8.0 – Final Targeted Patch (Candidate Pair Reconciliation in batch_row_results, Source-Specific Import Batches)

---

## 1. Domain 1: User & Access Control (5 Tables)

### 1.1. Table: `users`
Represents named administrative and operational staff members in the system.
- `id` (UUID, Primary Key): Unique internal user identifier.
- `username` (VARCHAR(100), UNIQUE, NOT NULL): System login name.
- `email` (VARCHAR(255), UNIQUE, NOT NULL): Official enterprise email address.
- `password_hash` (VARCHAR(255), NOT NULL): Salted bcrypt/argon2 password hash.
- `full_name` (VARCHAR(255), NOT NULL): Legal full name of the employee.
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'ACTIVE'): Status (`ACTIVE`, `REVOKED`, `SUSPENDED`).
- `is_active` (BOOLEAN, NOT NULL, DEFAULT TRUE): Active flag for immediate access revocation.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()): User creation timestamp.
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()): Last modification timestamp.

### 1.2. Table: `roles`
Stores standard system roles.
- `id` (UUID, Primary Key): Role unique identifier.
- `role_code` (VARCHAR(50), UNIQUE, NOT NULL): Role code (`DATA_STEWARD`, `APPROVER`, `ADMINISTRATOR`).
- `role_name` (VARCHAR(100), NOT NULL): Human-readable role label.
- `description` (TEXT, NULL): Detailed description of role boundaries.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 1.3. Table: `permissions`
Granular functional permissions enforced server-side.
- `id` (UUID, Primary Key): Permission unique identifier.
- `permission_code` (VARCHAR(100), UNIQUE, NOT NULL): E.g., `INTAKE:UPLOAD`, `CANDIDATE:PROPOSE`, `CANONICAL:APPROVE`, `CANONICAL:SPLIT`, `EXPORT:CROSSWALK`.
- `resource` (VARCHAR(50), NOT NULL): Target entity or API resource.
- `action` (VARCHAR(50), NOT NULL): Action verb (`READ`, `PROPOSE`, `APPROVE`, `REVOKE`, `EXPORT`).
- `description` (TEXT, NULL).

### 1.4. Table: `user_roles`
Mapping table assigning roles to users.
- `user_id` (UUID, FK -> `users.id`, Composite PK).
- `role_id` (UUID, FK -> `roles.id`, Composite PK).
- `granted_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `granted_by` (UUID, FK -> `users.id`, NULL).

### 1.5. Table: `role_permissions`
Mapping table assigning granular permissions to roles.
- `role_id` (UUID, FK -> `roles.id`, Composite PK).
- `permission_id` (UUID, FK -> `permissions.id`, Composite PK).
- `granted_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

---

## 2. Domain 2: Source & Intake Management (8 Tables)

### 2.1. Table: `source_systems`
Registry of upstream authoritative sources.
- `id` (UUID, Primary Key): System identifier.
- `source_code` (VARCHAR(50), UNIQUE, NOT NULL): Code identifier (`CRM_A`, `CRM_B`, `CRM_C`).
- `source_name` (VARCHAR(150), NOT NULL): Descriptive source system name.
- `entity_type` (VARCHAR(50), NOT NULL): Supported type (`ACCOUNT`, `CONTACT`).
- `schema_version` (VARCHAR(20), NOT NULL, DEFAULT '1.0'): Contract version.
- `is_active` (BOOLEAN, NOT NULL, DEFAULT TRUE): Intake availability flag.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `UNIQUE (source_code)`
  - `UNIQUE (id, entity_type)` (Prerequisite key for composite FK intake pool isolation).

### 2.2. Table: `import_batches`
Tracks individual intake file uploads and batch manifests.
- `id` (UUID, Primary Key): Batch identifier.
- `source_system_id` (UUID, FK -> `source_systems.id`, NULL): Source anchor. Required for all operational intake batches; NULL is strictly permitted ONLY for `batch_type = 'UNMAPPED_QUARANTINE'` to isolate source records missing a verifiable source system without fabricating a fake source.
- `batch_type` (VARCHAR(50), NOT NULL, DEFAULT 'DAILY_SNAPSHOT'): (`INITIAL_FULL`, `DAILY_SNAPSHOT`, `INCREMENTAL`, `LEGACY_MIGRATION`, `UNMAPPED_QUARANTINE`).
- `file_name` (VARCHAR(255), NOT NULL): Uploaded file name or migration intake identifier.
- `file_checksum` (VARCHAR(64), NOT NULL): SHA-256 file checksum preventing redundant loads.
- `total_rows` (INTEGER, NOT NULL, DEFAULT 0).
- `accepted_rows` (INTEGER, NOT NULL, DEFAULT 0).
- `rejected_rows` (INTEGER, NOT NULL, DEFAULT 0).
- `quarantined_rows` (INTEGER, NOT NULL, DEFAULT 0).
- `batch_status` (VARCHAR(50), NOT NULL, DEFAULT 'PROCESSING'): (`PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `QUARANTINED`).
- `extraction_at` (TIMESTAMP WITH TIME ZONE, NULL): Source extraction timestamp (staleness check).
- `imported_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `uploaded_by` (UUID, FK -> `users.id`, NOT NULL).
- `error_summary` (TEXT, NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `CONSTRAINT ck_import_batch_source_mapping CHECK ((batch_type = 'UNMAPPED_QUARANTINE' AND source_system_id IS NULL) OR (batch_type <> 'UNMAPPED_QUARANTINE' AND source_system_id IS NOT NULL))`: Enforces that operational intake batches always possess an authentic source system, while quarantine batches for unmapped source data never fabricate fake sources.
  - `CONSTRAINT uq_import_batch_system UNIQUE (id, source_system_id)`: Prerequisite unique key supporting Composite Foreign Key in `run_sources`.
- *Source-Specific Intake Architecture*: Dedicated import batches (`BATCH_CRM_A`, `BATCH_CRM_B`, `BATCH_CRM_C`) process source records for their respective pools (`ACCOUNT` vs `CONTACT`). Records with missing/unrecognized source systems are routed to `BATCH_UNMAPPED_QUARANTINE` (`source_system_id = NULL`) without fabricating fake systems. Candidate pairs are multi-source comparison edges and are strictly governed by `matching_runs`, not `import_batches`.

### 2.3. Table: `source_records`
Persistent, stable identity anchor of a source CRM record.
- `id` (UUID, Primary Key): Internal unique anchor identifier.
- `source_system_id` (UUID, NOT NULL).
- `source_key` (VARCHAR(100), NOT NULL): Immutable key from source system (e.g., `ACC-1042`).
- `entity_type` (VARCHAR(50), NOT NULL): High-level entity pool (`ACCOUNT`, `CONTACT`).
- `entity_subtype` (VARCHAR(50), NULL): Subtype (`COMPANY`, `BRANCH`, `SITE`, `PERSON`).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Composite Foreign Keys*:
  - `FOREIGN KEY (source_system_id, entity_type) REFERENCES source_systems (id, entity_type) ON DELETE RESTRICT` (Enforces intake pool consistency; ACCOUNT sources cannot contain CONTACT records and vice versa).
- *Constraints*:
  - `UNIQUE (source_system_id, entity_type, source_key)`
  - `UNIQUE (id, entity_type)` (Supports Composite Foreign Keys for cross-table pool isolation).

### 2.4. Table: `source_record_versions`
Temporal, immutable version storage of raw source payload.
- `id` (UUID, Primary Key): Version identifier.
- `source_record_id` (UUID, FK -> `source_records.id`, NOT NULL).
- `version_number` (INTEGER, NOT NULL): Sequential version (1, 2, ...).
- `import_batch_id` (UUID, FK -> `import_batches.id`, NOT NULL).
- `raw_payload` (JSONB, NOT NULL): Unmodified raw row dictionary as extracted.
- `checksum` (VARCHAR(64), NOT NULL): SHA-256 hash of raw row payload.
- `row_anchor` (VARCHAR(100), NULL): Line index / CSV row number anchor.
- `extraction_at` (TIMESTAMP WITH TIME ZONE, NULL).
- `imported_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `effective_from` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `effective_to` (TIMESTAMP WITH TIME ZONE, NULL): NULL indicates current version.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `CHECK (effective_to IS NULL OR effective_to > effective_from)` (strictly positive duration).
  - `UNIQUE (source_record_id, version_number)`
  - `UNIQUE (id, source_record_id)` (Supports Composite Foreign Key in canonical memberships).
  - *Temporal Integrity Architecture*: Version sequencing is strictly governed by `version_number` and `imported_at`. An engine-level exclusion constraint (`EXCLUDE USING GIST`) is intentionally omitted on `[effective_from, effective_to)` to prevent intake failure when upstream CRM systems provide retroactive corrections or overlapping attribute validity dates. Intentionally preserves raw payloads without loss (DAT 01, DAT 02).

### 2.5. Table: `batch_row_results`
Reconciliation audit log of every processed intake source record row.
- `id` (UUID, Primary Key).
- `import_batch_id` (UUID, FK -> `import_batches.id`, NOT NULL).
- `row_number` (INTEGER, NOT NULL): Source CSV row index or legacy source record ID.
- `source_key` (VARCHAR(100), NULL): Extracted key or NULL if missing/unparseable.
- `row_status` (VARCHAR(50), NOT NULL): (`ACCEPTED`, `QUARANTINED`, `REJECTED`).
- `validation_errors` (JSONB, NULL): Detailed field validation failures and quarantine diagnostic details.
- `quarantine_reason` (TEXT, NULL): Reason for isolation (e.g., `UNIDENTIFIED_SOURCE_SYSTEM`, `DUPLICATE_SOURCE_KEY_IN_SOURCE`, `UNRESOLVED_ENTITY_TYPE_AMBIGUITY`).
- `source_record_id` (UUID, FK -> `source_records.id`, NULL).
- `source_record_version_id` (UUID, FK -> `source_record_versions.id`, NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `UNIQUE (import_batch_id, row_number)`: Enforces that each intake row is evaluated and recorded exactly once per batch, mathematically guaranteeing zero double-counting in intake reconciliation.
- *Intake Row Reconciliation Architecture*: Serves as the complete row-level audit ledger for all raw source intake batches (including unmapped source quarantine batches). Candidate pairs are compared across source records and audited within their matching run and legacy staging table, not as single-source intake rows.

### 2.6. Table: `source_identifiers`
Discrete identity identifiers (Tax IDs, National IDs, Passports).
- `id` (UUID, Primary Key).
- `source_record_id` (UUID, FK -> `source_records.id`, NOT NULL).
- `source_record_version_id` (UUID, FK -> `source_record_versions.id`, NOT NULL).
- `identifier_type` (VARCHAR(50), NOT NULL): E.g., `TAX_ID_10`, `TAX_ID_13`, `BUSINESS_REG_NO`.
- `identifier_value` (VARCHAR(100), NOT NULL): Exact formatted identifier.
- `issuer` (VARCHAR(100), NULL): E.g., `VN_TAX_AUTHORITY`.
- `jurisdiction` (VARCHAR(10), NOT NULL, DEFAULT 'VN').
- `entity_level` (VARCHAR(50), NOT NULL, DEFAULT 'LEGAL_ENTITY'): (`LEGAL_ENTITY`, `BRANCH`, `REPRESENTATIVE`).
- `verification_status` (VARCHAR(50), NOT NULL, DEFAULT 'SUPPLIED'): (`SUPPLIED`, `FORMAT_VALID`, `MANUALLY_VERIFIED`).
- `source_field` (VARCHAR(50), NOT NULL): Source column name where extracted.
- `valid_from` (TIMESTAMP WITH TIME ZONE, NULL).
- `valid_to` (TIMESTAMP WITH TIME ZONE, NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 2.7. Table: `matching_runs`
Manifest of an entity resolution execution or historical candidate pairs consolidation.
- `id` (UUID, Primary Key).
- `run_code` (VARCHAR(50), UNIQUE, NOT NULL): E.g., `RUN-20261113-001`, `MIG-0008-HISTORICAL-PAIRS`.
- `entity_pool` (VARCHAR(50), NOT NULL): Pool boundary (`ACCOUNT`, `CONTACT`).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'PENDING'): (`PENDING`, `RUNNING`, `COMPLETED`, `HELD_CEILING_BREACH`, `FAILED`).
- `policy_id` (UUID, FK -> `normalization_policies.id`, NOT NULL): Normalization policy governing matching rule thresholds.
- `total_candidates` (INTEGER, NOT NULL, DEFAULT 0): Count of candidate pairs generated or migrated.
- `ceiling_breached` (BOOLEAN, NOT NULL, DEFAULT FALSE): Set TRUE if candidates exceed 200,000.
- `started_at` (TIMESTAMP WITH TIME ZONE, NULL).
- `completed_at` (TIMESTAMP WITH TIME ZONE, NULL).
- `executed_by` (UUID, FK -> `users.id`, NOT NULL): Operator or migration administrator ID.
- `notes` (TEXT, NULL): Execution notes or migration consolidation context (e.g., historical run details).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 2.8. Table: `run_sources`
Binds snapshots from required source systems into a coherent run manifest.
- `id` (UUID, Primary Key).
- `matching_run_id` (UUID, FK -> `matching_runs.id`, NOT NULL).
- `source_system_id` (UUID, NOT NULL).
- `import_batch_id` (UUID, NOT NULL).
- `snapshot_cutoff` (TIMESTAMP WITH TIME ZONE, NOT NULL).
- `is_complete` (BOOLEAN, NOT NULL, DEFAULT TRUE).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Composite Foreign Key*:
  - `FOREIGN KEY (import_batch_id, source_system_id) REFERENCES import_batches (id, source_system_id) ON DELETE RESTRICT`: **Guarantees that `import_batch_id` strictly belongs to `source_system_id`**, eliminating any possibility of misattributing batches between source systems at the database engine tier.
- *Constraints*:
  - `UNIQUE (matching_run_id, import_batch_id)`: Permits a matching run to incorporate **multiple batches belonging to the same source system** (e.g. historical baseline + delta batches), while strictly preventing the duplicate inclusion of the same batch in a single run.
- *Cross-Batch Lineage Correlation Architecture*: Relational link enabling multi-batch executions (`BATCH_CRM_A`, `BATCH_CRM_B`, `BATCH_CRM_C`) to be tied to a unified `matching_runs` manifest with strict engine-level batch-source parity.

---

## 3. Domain 3: Normalization & Matching (5 Tables)

### 3.1. Table: `normalization_policies`
Versioning of normalization parameter sets and rules.
- `id` (UUID, Primary Key).
- `policy_name` (VARCHAR(100), NOT NULL): E.g., `DEFAULT_VN_INDUSTRIAL_POLICY`.
- `version` (INTEGER, NOT NULL): Integer version sequence.
- `configuration` (JSONB, NOT NULL): Weights, thresholds (65.0 suspected, 85.0 high), phonetic/token sort flags.
- `effective_from` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `effective_to` (TIMESTAMP WITH TIME ZONE, NULL).
- `created_by` (UUID, FK -> `users.id`, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraint*: `UNIQUE (policy_name, version)`.

### 3.2. Table: `normalized_features`
Standardized feature representations derived from raw record versions.
- `id` (UUID, Primary Key).
- `source_record_version_id` (UUID, FK -> `source_record_versions.id`, NOT NULL).
- `normalization_policy_id` (UUID, FK -> `normalization_policies.id`, NOT NULL).
- `field_name` (VARCHAR(50), NOT NULL): E.g., `legal_name`, `phone`, `tax_code`, `address`.
- `raw_value` (TEXT, NULL): Value prior to transformation.
- `normalized_value` (TEXT, NULL): Normalized canonical form (e.g., NFC, lower, accent-preserved).
- `feature_status` (VARCHAR(50), NOT NULL, DEFAULT 'VALID'): (`VALID`, `MALFORMED_UNUSABLE`, `EMPTY`).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 3.3. Table: `candidate_pairs`
Generated candidate comparison edges between two records.
- `id` (UUID, Primary Key).
- `matching_run_id` (UUID, FK -> `matching_runs.id`, NOT NULL).
- `left_source_record_id` (UUID, NOT NULL).
- `right_source_record_id` (UUID, NOT NULL).
- `entity_type` (VARCHAR(50), NOT NULL): Must match both records (`ACCOUNT` or `CONTACT`).
- `total_score` (NUMERIC(5, 2), NOT NULL): Similarity ranking score (0.00 to 99.00).
- `ranking_category` (VARCHAR(50), NOT NULL): (`HIGH_CONFIDENCE`, `SUSPECTED_DUPLICATE`, `POTENTIAL_RELATIONSHIP`).
- `decision_status` (VARCHAR(50), NOT NULL, DEFAULT 'NEW'): (`NEW`, `UNDER_REVIEW`, `DECIDED`, `SUPPRESSED`).
- `conflict_flags` (JSONB, NULL): Flags such as `TAX_ID_BRANCH_MISMATCH`, `DIFFERENT_PROVINCE`.
- `policy_version` (INTEGER, NOT NULL).
- `is_migrated_legacy` (BOOLEAN, NOT NULL, DEFAULT FALSE): Set TRUE for records imported from legacy table.
- `legacy_pair_id` (INTEGER, NULL): Integer primary key from `legacy_candidate_pairs.id` if migrated. Provides a reliable, indexed 1:1 anchor between legacy pairs and new candidate pairs without string concatenation or truncation risks.
- `legacy_reasons_raw` (TEXT, NULL): Verbatim raw legacy text reasons.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Composite Foreign Keys*:
  - `FOREIGN KEY (left_source_record_id, entity_type) REFERENCES source_records (id, entity_type)`
  - `FOREIGN KEY (right_source_record_id, entity_type) REFERENCES source_records (id, entity_type)`
- *Constraints*:
  - `CHECK (left_source_record_id < right_source_record_id)` (Canonical pair ordering).
  - `UNIQUE (matching_run_id, left_source_record_id, right_source_record_id)`.
  - `UNIQUE (legacy_pair_id)` (Unique constraint enforcing 1:1 mapping between legacy pair and migrated candidate pair).

### 3.4. Table: `candidate_blocking_paths`
All blocking rules that captured this candidate pair.
- `id` (UUID, Primary Key).
- `candidate_pair_id` (UUID, FK -> `candidate_pairs.id`, NOT NULL).
- `blocking_key_name` (VARCHAR(100), NOT NULL): E.g., `TAX_ID_ROOT`, `PHONE_EXACT`, `BRAND_PROVINCE`.
- `blocking_value` (VARCHAR(255), NOT NULL): Hash or string value evaluated.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 3.5. Table: `candidate_pair_evidence`
Granular, explainable feature comparison evidence for audit and review.
- `id` (UUID, Primary Key).
- `candidate_pair_id` (UUID, FK -> `candidate_pairs.id`, NOT NULL).
- `field_name` (VARCHAR(50), NOT NULL): E.g., `legal_name`, `tax_id`, `phone`, `email`, `legacy_reasons`.
- `left_raw_value` (TEXT, NULL).
- `right_raw_value` (TEXT, NULL).
- `left_normalized_value` (TEXT, NULL).
- `right_normalized_value` (TEXT, NULL).
- `similarity_score` (NUMERIC(5, 2), NULL): Individual field metric (NULL for legacy unstructured evidence).
- `evidence_direction` (VARCHAR(20), NULL): (`POSITIVE`, `NEGATIVE`, `NEUTRAL`) or NULL for legacy evidence.
- `evidence_weight` (NUMERIC(5, 2), NULL): Weight contribution (NULL for legacy evidence).
- `explanation` (TEXT, NULL): Human-readable breakdown.
- `policy_version` (INTEGER, NULL): NULL indicates unversioned legacy evidence.
- `is_legacy_evidence` (BOOLEAN, NOT NULL, DEFAULT FALSE).
- `provenance` (VARCHAR(50), NOT NULL, DEFAULT 'MATCHING_ENGINE'): (`MATCHING_ENGINE`, `MANUAL_STEWARD`, `LEGACY_MIGRATION`).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `CHECK (is_legacy_evidence = TRUE OR (evidence_direction IS NOT NULL AND evidence_direction IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')))`
  - `CHECK (is_legacy_evidence = TRUE OR (evidence_weight IS NOT NULL AND policy_version IS NOT NULL))`

---

## 4. Domain 4: Cluster & Human Review (5 Tables)

### 4.1. Table: `candidate_clusters`
Connected subgraphs formed by candidate pairs for collective review.
- `id` (UUID, Primary Key).
- `matching_run_id` (UUID, FK -> `matching_runs.id`, NOT NULL).
- `cluster_code` (VARCHAR(50), UNIQUE, NOT NULL): E.g., `CLS-20261113-0001`.
- `entity_type` (VARCHAR(50), NOT NULL): (`ACCOUNT`, `CONTACT`).
- `review_status` (VARCHAR(50), NOT NULL, DEFAULT 'NEW'): (`NEW`, `ASSIGNED`, `UNDER_REVIEW`, `RESOLVED`, `CONFLICT_SPLIT`).
- `member_count` (INTEGER, NOT NULL, DEFAULT 0).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraint*: `UNIQUE (id, entity_type)` (Supports Composite FK for member isolation).

### 4.2. Table: `candidate_cluster_members`
Association between a source record and a candidate cluster.
- `id` (UUID, Primary Key).
- `candidate_cluster_id` (UUID, NOT NULL).
- `source_record_id` (UUID, NOT NULL).
- `entity_type` (VARCHAR(50), NOT NULL).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'ACTIVE'): (`ACTIVE`, `EXCLUDED_BY_NEGATIVE_EVIDENCE`).
- `joined_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `left_at` (TIMESTAMP WITH TIME ZONE, NULL).
- *Composite Foreign Keys*:
  - `FOREIGN KEY (candidate_cluster_id, entity_type) REFERENCES candidate_clusters (id, entity_type)`
  - `FOREIGN KEY (source_record_id, entity_type) REFERENCES source_records (id, entity_type)`
- *Constraint*: `UNIQUE (candidate_cluster_id, source_record_id)`.

### 4.3. Table: `review_tasks`
Operational work items assigned to Data Stewards and Approvers.
- `id` (UUID, Primary Key).
- `candidate_pair_id` (UUID, FK -> `candidate_pairs.id`, NULL).
- `candidate_cluster_id` (UUID, FK -> `candidate_clusters.id`, NULL).
- `task_type` (VARCHAR(50), NOT NULL): (`PAIR_REVIEW`, `CLUSTER_REVIEW`, `SPLIT_ADJUDICATION`).
- `priority_tier` (VARCHAR(20), NOT NULL, DEFAULT 'MEDIUM'): (`HIGH`, `MEDIUM`, `LOW`).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'NEW'): (`NEW`, `UNDER_REVIEW`, `APPROVED_DUPLICATE`, `APPROVED_RELATIONSHIP`, `REJECTED`, `DEFERRED`, `SUPERSEDED`).
- `assigned_steward_id` (UUID, FK -> `users.id`, NULL).
- `assigned_approver_id` (UUID, FK -> `users.id`, NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Strict Target Exclusivity Constraint*:
  ```sql
  CHECK (
    (task_type = 'PAIR_REVIEW' AND candidate_pair_id IS NOT NULL AND candidate_cluster_id IS NULL)
    OR
    (task_type IN ('CLUSTER_REVIEW', 'SPLIT_ADJUDICATION') AND candidate_cluster_id IS NOT NULL AND candidate_pair_id IS NULL)
  )
  ```

### 4.4. Table: `review_decisions`
Immutable, append-only history of steward proposals and approver decisions.
- `id` (UUID, Primary Key).
- `review_task_id` (UUID, FK -> `review_tasks.id`, NOT NULL).
- `candidate_pair_id` (UUID, FK -> `candidate_pairs.id`, NULL).
- `proposed_decision` (VARCHAR(50), NOT NULL): (`SAME_ENTITY`, `RELATED_DISTINCT`, `DISTINCT`, `INSUFFICIENT_EVIDENCE`).
- `final_decision` (VARCHAR(50), NULL): (`SAME_ENTITY`, `RELATED_DISTINCT`, `DISTINCT`, `INSUFFICIENT_EVIDENCE`).
- `decision_reason` (TEXT, NOT NULL).
- `evidence_snapshot` (JSONB, NOT NULL): Frozen snapshot of evidence evaluated.
- `proposed_by` (UUID, FK -> `users.id`, NOT NULL): Data Steward user.
- `approved_by` (UUID, FK -> `users.id`, NULL): Approver user.
- `decision_status` (VARCHAR(50), NOT NULL, DEFAULT 'PROPOSED'): (`PROPOSED`, `APPROVED`, `REJECTED`, `SUPERSEDED`).
- `decided_at` (TIMESTAMP WITH TIME ZONE, NULL).
- `superseded_by` (UUID, FK -> `review_decisions.id`, NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `CHECK (approved_by IS NULL OR proposed_by <> approved_by)` (Strict database-level prevention of self-approval).
  - `UNIQUE (id, approved_by)` (Supports composite FK in canonical memberships and entity relationships).

### 4.5. Table: `pair_decision_constraints`
Persistent memory of confirmed DISTINCT pairs to block future transitive links.
- `id` (UUID, Primary Key).
- `left_source_record_id` (UUID, FK -> `source_records.id`, NOT NULL).
- `right_source_record_id` (UUID, FK -> `source_records.id`, NOT NULL).
- `constraint_type` (VARCHAR(50), NOT NULL, DEFAULT 'CONFIRMED_DISTINCT'): (`CONFIRMED_DISTINCT`, `BLOCKED_RELATIONSHIP`).
- `established_by_decision_id` (UUID, FK -> `review_decisions.id`, NOT NULL).
- `valid_from` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `valid_to` (TIMESTAMP WITH TIME ZONE, NULL).
- `is_active` (BOOLEAN, NOT NULL, DEFAULT TRUE).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraint*: `CHECK (left_source_record_id < right_source_record_id)`.
- *Constraint*: `UNIQUE (left_source_record_id, right_source_record_id, valid_from)`.

---

## 5. Domain 5: Canonical Resolution & Hierarchy (5 Tables)

### 5.1. Table: `canonical_entities`
Internal unified master identity representation.
- `id` (UUID, Primary Key).
- `canonical_code` (VARCHAR(50), UNIQUE, NOT NULL): Immutable identifier (e.g., `CAN-ACC-A8F12C90`, `CAN-CON-B3E491A2`).
- `entity_type` (VARCHAR(50), NOT NULL): (`ACCOUNT`, `CONTACT`).
- `entity_subtype` (VARCHAR(50), NULL): (`COMPANY`, `BRANCH`, `SITE`, `PERSON`).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'ACTIVE'): (`ACTIVE`, `RETIRED_SPLIT`, `RETIRED_MERGED`).
- `created_by` (UUID, FK -> `users.id`, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `updated_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraint*: `UNIQUE (id, entity_type)` (Supports composite FK for membership isolation).

### 5.2. Table: `canonical_memberships`
Temporal membership connecting a source record to a canonical entity.
- `id` (UUID, Primary Key).
- `canonical_entity_id` (UUID, NOT NULL).
- `source_record_id` (UUID, NOT NULL).
- `source_record_version_id` (UUID, NOT NULL).
- `entity_type` (VARCHAR(50), NOT NULL).
- `valid_from` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `valid_to` (TIMESTAMP WITH TIME ZONE, NULL): NULL indicates currently valid.
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'USABLE'): (`USABLE`, `HELD`, `SUPERSEDED`).
- `decision_id` (UUID, NOT NULL).
- `approved_by` (UUID, NOT NULL).
- `decision_reason` (TEXT, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Composite Foreign Keys*:
  - `FOREIGN KEY (canonical_entity_id, entity_type) REFERENCES canonical_entities (id, entity_type)`
  - `FOREIGN KEY (source_record_id, entity_type) REFERENCES source_records (id, entity_type)`
  - `FOREIGN KEY (source_record_version_id, source_record_id) REFERENCES source_record_versions (id, source_record_id)`
  - `FOREIGN KEY (decision_id, approved_by) REFERENCES review_decisions (id, approved_by)`
- *Temporal Non-Overlap Guarantee*:
  - Interval convention: Half-open `[valid_from, valid_to)` (inclusive start, exclusive end).
  - PostgreSQL Constraint:
    ```sql
    EXCLUDE USING GIST (
      source_record_id WITH =,
      tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)') WITH &&
    ) WHERE (status = 'USABLE');
    ```
  - SQLite Constraint: Trigger `trg_prevent_membership_temporal_overlap` and transactional check (operates on standardized `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC timestamps with sentinel `'9999-12-31T23:59:59.999999Z'`).
  - `CHECK (valid_to IS NULL OR valid_to > valid_from)` (strictly positive duration; empty intervals `[t, t)` rejected).

### 5.3. Table: `canonical_fields`
Golden record field values selected for the canonical entity.
- `id` (UUID, Primary Key).
- `canonical_entity_id` (UUID, FK -> `canonical_entities.id`, NOT NULL).
- `field_name` (VARCHAR(50), NOT NULL): E.g., `canonical_name`, `primary_tax_id`, `primary_phone`.
- `selected_value` (TEXT, NOT NULL): The chosen golden value.
- `valid_from` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `valid_to` (TIMESTAMP WITH TIME ZONE, NULL).
- `decision_id` (UUID, FK -> `review_decisions.id`, NOT NULL).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'ACTIVE'): (`ACTIVE`, `SUPERSEDED`).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraints*:
  - `CHECK (valid_to IS NULL OR valid_to > valid_from)` (strictly positive duration).
  - *Temporal Integrity Architecture*: Governed by RFP REV 04 (Single Active Golden Value per Canonical Entity & Field Name). Guarantees at most 1 active golden value via partial unique index `uq_single_active_canonical_field`. Historical temporal exclusion across `SUPERSEDED` rows is intentionally omitted to allow retroactive timeline governance corrections and backfilled audit provenance without compromising active MDM lookup performance.
- *Partial Unique Index*:
  ```sql
  CREATE UNIQUE INDEX uq_single_active_canonical_field
  ON canonical_fields (canonical_entity_id, field_name)
  WHERE status = 'ACTIVE' AND valid_to IS NULL;
  ```

### 5.4. Table: `canonical_field_provenance`
Detailed lineage of how a canonical field value was selected.
- `id` (UUID, Primary Key).
- `canonical_field_id` (UUID, FK -> `canonical_fields.id`, NOT NULL).
- `source_record_id` (UUID, FK -> `source_records.id`, NOT NULL).
- `source_record_version_id` (UUID, FK -> `source_record_versions.id`, NOT NULL).
- `source_field` (VARCHAR(50), NOT NULL).
- `original_value` (TEXT, NULL).
- `selected_value` (TEXT, NOT NULL).
- `precedence_rule` (VARCHAR(100), NOT NULL): E.g., `SOURCE_A_ERP_OVER_B`, `MANUAL_OVERRIDE`.
- `override_reason` (TEXT, NULL).
- `effective_date` (TIMESTAMP WITH TIME ZONE, NOT NULL).
- `approved_by` (UUID, FK -> `users.id`, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 5.5. Table: `entity_relationships`
Directed structural and affiliation relationships between distinct canonical entities.
- `id` (UUID, Primary Key).
- `from_canonical_id` (UUID, NOT NULL).
- `from_entity_type` (VARCHAR(50), NOT NULL).
- `to_canonical_id` (UUID, NOT NULL).
- `to_entity_type` (VARCHAR(50), NOT NULL).
- `relationship_type` (VARCHAR(50), NOT NULL): (`PARENT_OF`, `BRANCH_OF`, `SITE_OF`, `AFFILIATED_WITH`).
- `direction` (VARCHAR(20), NOT NULL, DEFAULT 'DIRECTED'): (`DIRECTED`, `BIDIRECTIONAL`).
- `source_record_id` (UUID, FK -> `source_records.id`, NULL): Provenance record if supplied in source file.
- `valid_from` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `valid_to` (TIMESTAMP WITH TIME ZONE, NULL).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'ACTIVE'): (`ACTIVE`, `TERMINATED`, `SUPERSEDED`).
- `decision_id` (UUID, NOT NULL).
- `approved_by` (UUID, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Composite Foreign Keys*:
  - `FOREIGN KEY (from_canonical_id, from_entity_type) REFERENCES canonical_entities (id, entity_type)`
  - `FOREIGN KEY (to_canonical_id, to_entity_type) REFERENCES canonical_entities (id, entity_type)`
  - `FOREIGN KEY (decision_id, approved_by) REFERENCES review_decisions (id, approved_by)`
- *Constraints*:
  - `CHECK (valid_to IS NULL OR valid_to > valid_from)` (strictly positive duration).
  - `CHECK (from_canonical_id <> to_canonical_id)` (Self-loop prevention).
  - *Relationship Entity Type Compatibility Constraint*:
    ```sql
    CHECK (
      (relationship_type IN ('PARENT_OF', 'BRANCH_OF', 'SITE_OF')
         AND from_entity_type = 'ACCOUNT' AND to_entity_type = 'ACCOUNT')
      OR
      (relationship_type = 'AFFILIATED_WITH'
         AND (
           (from_entity_type = 'CONTACT' AND to_entity_type = 'ACCOUNT') OR
           (from_entity_type = 'ACCOUNT' AND to_entity_type = 'ACCOUNT') OR
           (from_entity_type = 'CONTACT' AND to_entity_type = 'CONTACT')
         ))
    )
    ```

---

## 6. Domain 6: Audit, Retention & Erasure Ledger (3 Tables)

### 6.1. Table: `audit_events`
Append-only tamper-evident audit ledger.
- `id` (UUID, Primary Key).
- `event_id` (VARCHAR(100), UNIQUE, NOT NULL): UUID string format.
- `actor_id` (UUID, FK -> `users.id`, NOT NULL).
- `actor_role` (VARCHAR(50), NOT NULL).
- `action` (VARCHAR(100), NOT NULL): E.g., `IMPORT:INGEST`, `MATCH:EXECUTE`, `REVIEW:PROPOSE`, `CANONICAL:APPROVE`, `CANONICAL:SPLIT`, `RETENTION:PURGE`.
- `target_type` (VARCHAR(50), NOT NULL): E.g., `IMPORT_BATCH`, `CANDIDATE_PAIR`, `CANONICAL_MEMBERSHIP`.
- `target_id` (VARCHAR(100), NOT NULL).
- `before_state` (JSONB, NULL).
- `after_state` (JSONB, NULL).
- `request_id` (VARCHAR(100), NULL): Correlation ID across API sessions.
- `related_decision_id` (UUID, FK -> `review_decisions.id`, NULL).
- `policy_version` (INTEGER, NULL).
- `reason` (TEXT, NULL).
- `is_migrated_legacy` (BOOLEAN, NOT NULL, DEFAULT FALSE).
- `hash_generated_at_migration` (BOOLEAN, NOT NULL, DEFAULT FALSE): Set TRUE for legacy rows hashed during migration.
- `previous_hash` (VARCHAR(64), NULL): Cryptographic chain hash of previous audit record.
- `record_hash` (VARCHAR(64), NOT NULL): SHA-256(previous_hash + actor_id + action + timestamp + payload).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 6.2. Table: `retention_policies`
Formal data retention schedules complying with Law 91/2025/QH15.
- `id` (UUID, Primary Key).
- `data_category` (VARCHAR(100), UNIQUE, NOT NULL): E.g., `RAW_IMPORT_BATCHES`, `UNDECIDED_FEATURES`, `APPROVED_MAPPINGS`, `AUDIT_LOGS`, `BACKUPS`.
- `retention_days` (INTEGER, NOT NULL): Target lifespan (e.g., 90 for raw batches, 365 for mappings, 35 for backups).
- `effective_date` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `legal_basis` (VARCHAR(255), NOT NULL): E.g., `LAW_91_2025_QH15_ART16`.
- `policy_owner` (VARCHAR(150), NOT NULL): Appointed Data Protection Officer / Business Owner.
- `approval_status` (VARCHAR(50), NOT NULL, DEFAULT 'PROPOSED'): (`PROPOSED`, `RATIFIED_BY_OWNER`).
- `review_date` (TIMESTAMP WITH TIME ZONE, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 6.3. Table: `deletion_ledger`
Tracking ledger for privacy erasures and retention enforcement.
- `id` (UUID, Primary Key).
- `request_code` (VARCHAR(100), UNIQUE, NOT NULL): E.g., `DEL-20261113-001`.
- `deletion_type` (VARCHAR(50), NOT NULL): (`RETENTION_SCHEDULE`, `LEGAL_ERASURE_REQUEST`, `CORRECTION`).
- `affected_target_type` (VARCHAR(50), NOT NULL).
- `affected_target_id` (VARCHAR(100), NOT NULL).
- `executed_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- `affected_data_scope` (JSONB, NOT NULL): Detailed JSON payload of purged keys.
- `execution_result` (VARCHAR(50), NOT NULL, DEFAULT 'SUCCESS'): (`SUCCESS`, `PARTIAL_FAILURE`).
- `approved_by` (UUID, FK -> `users.id`, NOT NULL).
- `backup_propagation_status` (VARCHAR(50), NOT NULL, DEFAULT 'PENDING_EXPIRY'): (`PENDING_EXPIRY`, `PURGED_FROM_BACKUP`).
- `backup_purged_at` (TIMESTAMP WITH TIME ZONE, NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

---

## 7. Domain 7: Export Management & Manifest (2 Tables)

### 7.1. Table: `export_jobs`
Coordinates crosswalk generation and external publication.
- `id` (UUID, Primary Key).
- `export_code` (VARCHAR(50), UNIQUE, NOT NULL): E.g., `EXP-20261113-0001`.
- `export_type` (VARCHAR(50), NOT NULL, DEFAULT 'CANONICAL_CROSSWALK_CSV'): (`CANONICAL_CROSSWALK_CSV`, `DECISION_DOSSIER_PDF`).
- `permitted_audience` (VARCHAR(100), NOT NULL): Designated consumer group (e.g., `ANALYTICS_BI`, `CRM_OPS`).
- `file_path` (VARCHAR(500), NOT NULL): Storage location.
- `file_checksum` (VARCHAR(64), NOT NULL): SHA-256 hash of generated artifact.
- `total_records_exported` (INTEGER, NOT NULL, DEFAULT 0).
- `status` (VARCHAR(50), NOT NULL, DEFAULT 'GENERATED'): (`GENERATED`, `SUPERSEDED_BY_REVERSAL`).
- `extraction_at` (TIMESTAMP WITH TIME ZONE, NOT NULL): As-of snapshot cutoff.
- `requested_by` (UUID, FK -> `users.id`, NOT NULL).
- `completed_at` (TIMESTAMP WITH TIME ZONE, NOT NULL).
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).

### 7.2. Table: `export_manifest_items`
Row-by-row manifest tracing every canonical membership included in an export.
- `id` (UUID, Primary Key).
- `export_job_id` (UUID, FK -> `export_jobs.id`, NOT NULL).
- `canonical_entity_id` (UUID, FK -> `canonical_entities.id`, NOT NULL).
- `source_record_id` (UUID, FK -> `source_records.id`, NOT NULL).
- `canonical_membership_id` (UUID, FK -> `canonical_memberships.id`, NOT NULL).
- `mapping_version` (INTEGER, NOT NULL, DEFAULT 1).
- `membership_status_at_export` (VARCHAR(50), NOT NULL, DEFAULT 'USABLE').
- `is_superseded` (BOOLEAN, NOT NULL, DEFAULT FALSE): Flipped to TRUE if the underlying membership is split or unlinked post-export.
- `created_at` (TIMESTAMP WITH TIME ZONE, NOT NULL, DEFAULT NOW()).
- *Constraint*: `UNIQUE (export_job_id, source_record_id)`.
