# DATABASE TESTING & VERIFICATION PLAN
## SongNhat CRM Duplicate Detection and Entity Resolution System
### Version: 8.5 – Final Targeted Patch (Legacy Entity-Type Compatibility, Full Endpoint Pool Validation & SQLite Transaction Verification)

---

## 1. Testing Framework & Status Terminology

Testing validates that database schemas, integrity constraints, and SQLAlchemy 2.0 models strictly enforce the mandatory rules of the SongNhat RFP.
- **Framework**: `pytest 8.3+` with SQLAlchemy test fixtures (`tmp_path` SQLite databases and isolated PostgreSQL test schemas).
- **Core Principle**: Schema enforcement must prevent illegal states at the database tier, independent of frontend or application API validation.

### Status Classification Standards
- **TEST_DESIGNED**: Detailed test scenario, input data, and expected assertions are fully specified.
- **AWAITING_PHASE_2**: Implementation awaiting Phase 2 model coding and Alembic migration deployment.
- **AWAITING_PHASE_5**: End-to-end workload and benchmark tests requiring populated 15,000 record test corpora.
- *Strict Rule*: No test is marked as PASSED until physical test execution logs and benchmark reports are produced.

---

## 2. Test Suite Architecture

```text
tests/
├── conftest.py                       # Fixtures: db_session, test_users, seed_policies
├── test_matching_pipeline.py         # Existing smoke test suite
├── test_db_migration_rollback.py     # Migration revisions, rollback safety, legacy data preservation
├── test_db_access_control.py         # RBAC, user permissions, Maker-Checker constraints
├── test_db_source_intake.py          # Lineage, versioning, checksum idempotency, quarantine
├── test_db_entity_type_isolation.py  # Account vs Contact pool segregation, relationships
├── test_db_matching_evidence.py      # Blocking paths, pair canonical ordering, evidence direction
├── test_db_review_workflow.py        # Independent approval, self-approval blockage, distinct constraints
├── test_db_canonical_lifecycle.py    # Temporal memberships, GiST exclusion, hold, split, unlink
├── test_db_audit_governance.py       # Append-only audit log, hash chaining, deletion ledger
└── test_db_export_manifest.py        # Crosswalk export filtering, exclusion of HELD records
```

---

## 3. Detailed Test Case Specifications & Constraint Mapping

### 3.1. Migration & Legacy Preservation Tests (`test_db_migration_rollback.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-MIG-01 | `test_migration_revision_order_and_rollback` | Alembic `downgrade` safety check | Revisions `0001`-`0007` and `0009` rollback cleanly; `0008` raises `RuntimeError` blocking automatic downgrade; rollback requires backup restore. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-02 | `test_legacy_reasons_preservation` | `candidate_pairs.legacy_reasons_raw` & `candidate_pair_evidence` | Raw text reason preserved verbatim; evidence line has `is_legacy_evidence = TRUE`, `provenance = 'LEGACY_MIGRATION'`; `similarity_score`, `evidence_direction`, `evidence_weight`, `policy_version` are strictly `NULL`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-03 | `test_legacy_audit_provenance_and_hash_flag` | `audit_events.is_migrated_legacy` & `hash_generated_at_migration` | Original audit log fields preserved; flags correctly mark hash as generated at migration instant without asserting pre-migration immutability. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-04 | `test_legacy_source_record_conservation_reconciliation` | Automated row conservation assertions across source batches | Asserts that `total_legacy_rows == total_evaluated_rows == migrated_count + quarantined_count + rejected_count`. Every legacy row is accounted for exactly once. `migrated_count` strictly equals physical `source_record_versions` (v1) count and distinct `source_records` count. Zero quarantined rows leak into `source_records`. Valid quarantine evaluates to `PASS`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-05 | `test_legacy_candidate_pair_quarantined_endpoint_handling` | Scenarios 2, 3, 4: Quarantined endpoint pairs | When one or both endpoints are in Quarantine, pair is NOT inserted into `candidate_pairs`; pair is audited and preserved in `legacy_candidate_pairs` and categorized as `PAIR_QUARANTINED_ENDPOINT` in reconciliation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-06 | `test_legacy_candidate_pair_cross_pool_rejection` | Scenario 7: Pool isolation & composite FK enforcement | Legacy candidate pairs connecting an Account to a Contact are rejected with `PAIR_REJECTED_CROSS_POOL_MISMATCH` and never inserted into `candidate_pairs`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-07 | `test_legacy_source_duplicate_or_invalid_key_quarantine` | Source pre-validation & de-duplication guard | Legacy records sharing identical `(source_system, source_key)` or missing source_key are routed to `QUARANTINED`/`REJECTED` in `batch_row_results` without arbitrary first-row picking; records lacking source_system route to `BATCH_UNMAPPED_QUARANTINE` with `source_system_id = NULL`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-08 | `test_legacy_candidate_pair_dangling_key_rejection` | Scenario 5: Missing / dangling endpoint keys | When a candidate pair references a `source_key` that does not exist in `legacy_source_records`, pair is categorized as `PAIR_REJECTED_DANGLING_KEY` and excluded from `candidate_pairs`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-09 | `test_legacy_candidate_pair_ambiguous_endpoint_quarantine` | Scenario 6: Ambiguous endpoint keys (multiple duplicates) | When an endpoint key matches multiple duplicate source records, pair is categorized as `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT` without arbitrary guessing and excluded from `candidate_pairs`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-10 | `test_legacy_candidate_pair_conservation_reconciliation` | Candidate pairs conservation under matching run governance | Asserts $\text{Total Legacy Pairs} = \text{Evaluated Pairs} = \sum \text{5 Mutually Exclusive Outcomes}$. Asserts `pair_migrated_count` strictly equals `COUNT(*) FROM candidate_pairs WHERE matching_run_id = :legacy_run_id AND is_migrated_legacy = TRUE`. Zero double-counting, zero assumption of CRM_A source ownership. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-11 | `test_source_specific_import_batches_and_unmapped_quarantine` | Source batches & unmapped source quarantine (Zero Fake Sources) | Verifies migration provisions separate batches for `CRM_A`, `CRM_B`, `CRM_C` and an unmapped quarantine batch (`source_system_id = NULL`); confirms `chk_import_batch_source` blocks NULL for operational batches while allowing it for quarantine. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-12 | `test_run_sources_batch_system_parity_and_multi_batch` | Batch-source parity composite FK & multi-batch linking | Verifies composite FK `(import_batch_id, source_system_id)` rejects mismatched batch-source pairs; verifies `UNIQUE (matching_run_id, import_batch_id)` permits linking multiple batches from same source system in one run. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-13 | `test_candidate_pair_invalid_endpoint_handling` | Quarantined / invalid source endpoint isolation | Asserts that when an endpoint row was quarantined during intake, pair is categorized as `PAIR_QUARANTINED_ENDPOINT` and not inserted into `candidate_pairs`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-14 | `test_source_key_collision_across_source_systems` | Multiplicity check across legacy source systems | When identical `source_key` exists in CRM_A and CRM_B ($L_{cnt} > 1$), endpoint cannot be uniquely resolved; pair is categorized as `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT` without guessing. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-15 | `test_ambiguous_endpoint_quarantine_isolation` | Zero speculation for non-unique endpoints | Asserts that ambiguous endpoint pairs are safely preserved in `legacy_candidate_pairs` and produce zero rows in `candidate_pairs`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-16 | `test_matching_runs_total_candidates_post_migration_accuracy` | Accurate candidate metrics after insertion | Verifies `matching_runs.total_candidates` is updated from 0 to the exact count of inserted candidate pairs; status transitions from `RUNNING` to `COMPLETED`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-17 | `test_legacy_to_physical_parity_assertion` | Directional parity from legacy to physical | Asserts that every legacy pair classified as `PAIR_MIGRATED` exists in `candidate_pairs` with matching `legacy_pair_id`, correct pool matching run, and canonical endpoints. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-18 | `test_physical_to_legacy_parity_assertion` | Directional parity from physical to legacy | Asserts that every physical `candidate_pairs` row created by migration 0008 maps to a valid legacy pair with zero orphans and zero duplicate `legacy_pair_id`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-19 | `test_orphan_migrated_candidate_pair_detection` | Zero orphan migrated pair invariant | Injects an artificial candidate pair with `is_migrated_legacy = TRUE` lacking legacy origin; asserts reconciliation assertion fails with `FAIL_PHYSICAL_TO_LEGACY`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-20 | `test_idempotent_migration_replay` | Rerun protection & unique constraints | Re-executing migration revision 0008 is safely blocked by unique constraints (`run_code`, `legacy_pair_id`) or pre-checks without creating duplicate records. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-21 | `test_matching_run_completion_and_transaction_atomicity` | Transactional rollback on mid-process failure | Verifies that matching runs start in `RUNNING` state; if an assertion fails before commit, entire transaction rolls back cleanly leaving zero partial records. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-22 | `test_mermaid_erd_syntax_validation` | Mermaid ER diagram syntax & structural integrity | Asserts `erd.mmd` parses with 0 errors via Mermaid parser; contains all 33 entities and 43 relationships; no independent relationship lines outside diagram. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-23 | `test_source_key_collision_across_source_systems` | Collision across CRMs with same source_key | Asserts that when CRM_A and CRM_B share identical `source_key` ($L_{cnt} > 1$), endpoint cannot be uniquely identified; pair is categorized as `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT` without guessing. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-24 | `test_source_record_resolution_multi_batch_immunity` | Immunity to multiple import batches | Verifies that `unique_migrated_sources` produces exactly one row per migrated source record even when a source system has multiple historical import batches. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-25 | `test_legacy_endpoint_source_system_parity` | Source-system parity enforcement | Asserts that an endpoint from CRM_A is strictly mapped to `source_records` belonging to CRM_A; never cross-mapped to CRM_B or CRM_C. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-26 | `test_idempotent_replay_completed_reconciled` | State B: Idempotent replay on completed runs | When both runs exist in `COMPLETED` state and reconciliation assertions evaluate to `PASS`, migration 0008 exits safely without duplicate inserts or modifications. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-27 | `test_idempotency_guard_single_matching_run_fail_closed` | State C: Partial run existence fail-closed | Asserts that when only one matching run exists (e.g. Account exists, Contact missing), migration raises `RuntimeError` and blocks automated recovery. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-28 | `test_idempotency_guard_corrupted_run_reconciliation_fail` | State D: Reconciliation failure fail-closed | Asserts that when runs exist but reconciliation assertions fail, migration raises `RuntimeError`, refuses to proceed, and directs restoration from backup. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-29 | `test_concurrent_migration_execution_serialization` | State E: Concurrency control & advisory locks | Verifies that concurrent execution acquires PostgreSQL advisory lock `pg_advisory_xact_lock` (or SQLite `BEGIN IMMEDIATE`), serializing workers and preventing race conditions. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-30 | `test_endpoint_physical_parity_mismatch_detection` | Endpoint physical parity assertion check | Injects a physical candidate pair with mismatched endpoint IDs; verifies `Assertion B (physical_to_legacy)` triggers `FAIL_PHYSICAL_TO_LEGACY`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-31 | `test_unmapped_discrepancy_triggers_transaction_rollback` | Internal technical discrepancy rollback | Asserts that if any pair evaluates to `PAIR_UNMAPPED_DISCREPANCY` (count > 0), reconciliation fails and the migration transaction executes immediate rollback. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-32 | `test_mermaid_actual_renderer_validation` | Actual graphical rendering via Mermaid CLI | Automated test harness executing `@mermaid-js/mermaid-cli` (`mmdc`) to render `erd.mmd` to SVG/PNG, verifying complete graphical rendering without runtime render errors. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-33 | `test_source_systems_entity_type_fallback_to_legacy` | Fallback and verification of entity pool | Asserts mapping correctly validates `sr.entity_type` against authoritative legacy type `ulk.legacy_entity_type` and `source_systems.entity_type` without arbitrary guessing. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-34 | `test_null_safe_endpoint_resolution` | NULL-safe handling in unique_migrated_sources | Verifies that unmapped or missing endpoints evaluate strictly to NULL and do not leak into migrated counts or falsely satisfy equality assertions. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-35 | `test_single_null_endpoint_physical_pair_rejection` | Single NULL endpoint physical detection | Injects a physical candidate pair where either `left_source_record_id` OR `right_source_record_id` is NULL; asserts `physical_endpoint_verification` evaluates to `is_endpoint_mismatch = 1`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-36 | `test_both_null_endpoints_physical_pair_rejection` | Both NULL endpoints physical detection | Injects a physical candidate pair where BOTH endpoints are NULL; asserts `physical_endpoint_verification` evaluates to `is_endpoint_mismatch = 1` and does not fall into `ELSE 0`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-37 | `test_physical_scope_column_consistency` | Comprehensive CTE column declaration | Asserts that all columns referenced in `physical_endpoint_verification` (`left_source_key`, `right_source_key`, `matched_legacy_id`, etc.) are explicitly declared in `physical_scope`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-38 | `test_candidate_pair_canonical_insert_ordering_parity` | Canonical ordering parity across operations | Verifies that candidate pair INSERT, unique constraint, physical endpoint verification, and reconciliation queries enforce identical `LEAST < GREATEST` ordering. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-39 | `test_alembic_transaction_locking_lifecycle` | Transaction locking lifecycle in Postgres & SQLite | Verifies PostgreSQL `pg_advisory_xact_lock` spans the entire transaction and auto-releases on commit/rollback; verifies SQLite avoids illegal nested `BEGIN IMMEDIATE` commands. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-40 | `test_mermaid_actual_rendering_environment_gate` | Environment gate check for graphical rendering | Documents environment readiness check for Mermaid CLI `mmdc` in CI/CD pipeline, verifying exit code and valid SVG structure when tools are available. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-41 | `test_legacy_entity_type_pool_mapping_compatibility` | Legacy entity type mapping (`COMPANY/BRANCH -> ACCOUNT`, `CONTACT -> CONTACT`) | Asserts that `unique_legacy_keys` correctly maps legacy entity types to standardized pools; rejects arbitrary `MIN(entity_type)` resolutions; enforces bidirectional compatibility. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-42 | `test_cross_pool_incompatible_legacy_intake_quarantine` | Intake quarantine on cross-pool incompatible legacy records | Asserts that a legacy `CONTACT` in CRM_A/CRM_B or legacy `COMPANY`/`BRANCH` in CRM_C is quarantined during intake and never linked into target `source_records`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-43 | `test_legacy_subtype_assumption_preservation_signoff` | Subtype preservation (`COMPANY` vs `BRANCH`) & Data Owner sign-off | Asserts that while `COMPANY` and `BRANCH` map to the unified `ACCOUNT` pool, the distinct subtype is preserved in `record_payload` without schema fragmentation, flagged for Data Owner sign-off. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-44 | `test_bilateral_endpoint_pool_symmetry_assertion` | Endpoint pool bilateral symmetry (`l_mig.entity_type = r_mig.entity_type`) | Asserts that `physical_endpoint_verification` strictly checks `l_mig.entity_type = r_mig.entity_type`; detects cross-pool discrepancy if endpoints diverge. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-45 | `test_bilateral_physical_pair_pool_parity_assertion` | Physical pair pool parity (`ps.entity_type = l_mig.entity_type` AND `ps.entity_type = r_mig.entity_type`) | Asserts that `physical_endpoint_verification` verifies candidate pair `entity_type` matches both endpoints, failing with `is_endpoint_mismatch = 1` if either diverges. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-46 | `test_null_safe_physical_endpoint_3vl_guard_verification` | Comprehensive 3VL NULL guard on both endpoints | Asserts that any NULL in `left_source_record_id`, `right_source_record_id`, `ps.entity_type`, `l_mig.entity_type`, or `r_mig.entity_type` triggers `is_endpoint_mismatch = 1` and never falls into `ELSE 0`. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-47 | `test_sqlite_driver_begin_immediate_engine_listener` | SQLite engine `begin` listener transaction hook | Verifies that on SQLite, immediate write locking is hooked via `@sa.event.listens_for(engine, "begin")`, avoiding DBAPI nested `BEGIN IMMEDIATE` errors (`cannot start a transaction within a transaction`). | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-48 | `test_sqlite_busy_timeout_deadlock_prevention` | SQLite connection busy timeout configuration | Verifies that `PRAGMA busy_timeout = 30000;` is applied on SQLite connect, gracefully handling lock contention and preventing premature `database is locked` errors under concurrency. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-49 | `test_mermaid_erd_phase2_cicd_visual_regression_pipeline` | Automated Mermaid CLI CI/CD visual test gate | Defines automated Phase 2 CI/CD pipeline step executing `mmdc -i erd.mmd -o erd.svg`, asserting zero render exit errors and validating SVG DOM structure. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MIG-50 | `test_multi_batch_import_invariance_on_legacy_parity` | Parity assertion invariance under multiple source batches | Asserts that `unique_migrated_sources` produces exactly one row per migrated endpoint without row multiplication when multiple import batches exist for a source system. | TEST_DESIGNED (Awaiting Phase 2) |

### 3.2. Source & Intake Tests (`test_db_source_intake.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-INT-01 | `test_source_record_unique_composite_key` | `uq_source_entity_key (source_system_id, entity_type, source_key)` | Duplicate key in same system raises IntegrityError; identical key in different system succeeds. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-INT-02 | `test_immutable_raw_payload_versioning` | `source_record_versions` version sequence | Version 1 raw JSON payload remains unchanged when Version 2 is inserted. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-INT-03 | `test_idempotent_batch_import` | `import_batches.file_checksum` lookup | Re-uploading identical file checksum is recognized as duplicate; no duplicate rows created. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-INT-04 | `test_batch_row_quarantine_isolation` | `batch_row_results.row_status = 'QUARANTINED'` | Row with missing required field is quarantined without aborting entire batch. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-INT-05 | `test_preserve_leading_zeros` | `source_identifiers` & `normalized_features` text types | Values like `'0101234567'` and `'0908123456'` preserve leading zero verbatim. | TEST_DESIGNED (Awaiting Phase 2) |

### 3.3. Entity Type & Pool Segregation Tests (`test_db_entity_type_isolation.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-POOL-01 | `test_account_contact_match_pool_rejection` | Composite FK `(left_source_record_id, entity_type)` and `(right_source_record_id, entity_type)` | Inserting pair with Account left and Contact right raises Foreign Key IntegrityError. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-02 | `test_cluster_member_entity_type_parity` | Composite FK `(candidate_cluster_id, entity_type)` and `(source_record_id, entity_type)` | Enrolling Contact record into Account cluster raises Foreign Key IntegrityError. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-03 | `test_canonical_membership_entity_type_parity` | Composite FK `(canonical_entity_id, entity_type)` and `(source_record_id, entity_type)` | Linking Account record to Contact canonical entity raises Foreign Key IntegrityError. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-04 | `test_entity_relationship_type_compatibility` | `chk_rel_type_entity_compat` | Inserting `PARENT_OF` between Contact entities raises CheckConstraint violation; `AFFILIATED_WITH` succeeds between Contact and Account. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-05 | `test_hierarchical_cycle_detection` | Recursive CTE check on `entity_relationships` | Inserting relationship creating A -> B -> A cycle is detected and aborted. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-06 | `test_concurrent_cycle_detection_serialization`| `pg_advisory_xact_lock(hashtext('hierarchy_dag_lock'))` | Concurrent transactions attempting reciprocal edges (Tx1: A->B, Tx2: B->A) are serialized; second transaction fails with cycle error. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-07 | `test_affiliation_cycle_allowed` | `relationship_type = 'AFFILIATED_WITH'` | Bidirectional affiliation links are permitted without triggering DAG tree violation or advisory locking. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-POOL-08 | `test_source_system_record_entity_type_parity` | Composite FK `(source_system_id, entity_type) -> source_systems (id, entity_type)` | Positive test: `ACCOUNT` source record successfully attaches to `ACCOUNT` source system. Negative test: Inserting `CONTACT` record into `ACCOUNT` source system (or `ACCOUNT` into `CONTACT`) raises Foreign Key `IntegrityError` (`fk_source_rec_system_pool`). | TEST_DESIGNED (Awaiting Phase 2) |

### 3.4. Matching & Evidence Tests (`test_db_matching_evidence.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-MAT-01 | `test_candidate_pair_canonical_ordering` | `chk_cand_pair_order (left_id < right_id)` | Inserting pair with `left_id >= right_id` raises CheckConstraint violation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MAT-02 | `test_multi_blocking_path_storage` | `candidate_blocking_paths` 1:N FK | Candidate pair correctly stores multiple blocking paths (Tax ID, Phone, Brand). | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MAT-03 | `test_directional_evidence_logging` | `chk_evidence_dir` | Evidence records accept only `POSITIVE`, `NEGATIVE`, `NEUTRAL` (or NULL for legacy evidence). | TEST_DESIGNED (Awaiting Phase 2) |
| TC-MAT-04 | `test_candidate_ceiling_breach_detection` | `matching_runs.ceiling_breached` flag | Over 200,000 candidates sets `ceiling_breached = TRUE` and holds run instead of silent truncation. | TEST_DESIGNED (Awaiting Phase 2) |

### 3.5. Review & Maker-Checker Workflow Tests (`test_db_review_workflow.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-REV-01 | `test_strict_no_self_approval_constraint` | `chk_no_self_approval (proposed_by <> approved_by)` | Proposal by `user_a` approved by `user_a` raises CheckConstraint violation at database tier. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-REV-02 | `test_independent_approver_success` | `review_decisions` commitment | Proposal by `user_a` approved by `user_b` successfully commits. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-REV-03 | `test_review_task_target_exclusivity` | `chk_task_target_exclusivity` | `PAIR_REVIEW` with cluster ID or `CLUSTER_REVIEW` with pair ID raises CheckConstraint violation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-REV-04 | `test_persistent_distinct_constraint` | `pair_decision_constraints` | Distinct decision creates persistent active constraint preventing future clustering. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-REV-05 | `test_single_active_cluster_participation` | Partial index `uq_single_active_cluster_member` | Enrolling an already enrolled active record into a second active cluster raises Unique violation. | TEST_DESIGNED (Awaiting Phase 2) |

### 3.6. Canonical Resolution & Temporal Integrity Tests (`test_db_canonical_lifecycle.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-CAN-01a| `test_canonical_membership_overlapping_intervals_rejected` | Postgres `EXCLUDE USING GIST` / SQLite trigger | Inserting two `USABLE` memberships with overlapping intervals (including backdated start `new.valid_from < old.valid_to`) for same source record raises exclusion/trigger violation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01b| `test_canonical_membership_non_overlapping_intervals_allowed` | Half-open intervals `[valid_from, valid_to)` | Inserting two `USABLE` memberships with distinct intervals `[t1, t2)` and `[t3, t4)` with chronological gap succeeds. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01c| `test_canonical_membership_adjacent_intervals_allowed` | Touching boundary points `[t1, t2)` and `[t2, t3)` | Adjacent half-open intervals (`old.valid_to == new.valid_from`) do not overlap and commit successfully. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01d| `test_canonical_membership_empty_interval_rejected` | `chk_temporal_validity (valid_to > valid_from)` | Inserting membership where `valid_to == valid_from` (empty degenerate interval `[t, t)`) raises CheckConstraint violation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01e| `test_canonical_membership_transition_held_and_adjudicated` | Transition to `HELD` & adjudication lifecycle | Updating status to `HELD` immediately excludes record from active CRM export crosswalk and exclusion constraint. Subsequent adjudication either returns status to `USABLE` (false alarm) or supersedes to `SUPERSEDED` with `valid_to = NOW()` and inserts new `USABLE` membership. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01f| `test_canonical_membership_transition_superseded_atomic` | Atomic supersession transaction | Transaction atomically updates existing row (`status = 'SUPERSEDED'`, `valid_to = NOW()`) and inserts replacement row (`status = 'USABLE'`, `valid_from = NOW()`). | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01g| `test_concurrent_membership_update_serialization` | Row-level locking (`FOR UPDATE`) / serializable transactions | Two concurrent transactions attempting to modify membership for the same source record are serialized via row locks, preventing race conditions. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-01h| `test_concurrent_initial_membership_insert_exclusion` | Postgres `EXCLUDE USING GIST` / SQLite trigger & transaction concurrency | Two concurrent transactions (Tx1, Tx2) attempt to insert overlapping `USABLE` memberships for a clean source record (no prior membership). PostgreSQL exclusion / SQLite trigger aborts one transaction; exactly one `USABLE` membership is committed with zero invalid overlap. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-02 | `test_single_active_canonical_field_constraint` | Partial index `uq_single_active_canonical_field` | Inserting two active values for same canonical entity and field name raises Unique violation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-03 | `test_canonical_version_binding` | Composite FK `(source_record_version_id, source_record_id)` | Linking a membership to a version ID belonging to another source record raises Foreign Key violation. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-04 | `test_canonical_approver_consistency` | Composite FK `(decision_id, approved_by)` | Membership recorded approver must match decision recorded approver. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-05 | `test_atomic_cluster_split_transaction` | Atomic transaction rollback on failure | Split marks old membership `SUPERSEDED`, creates new canonical entity and active membership. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-CAN-06 | `test_immutable_canonical_id_no_reuse` | `canonical_entities (canonical_code, status)` | Retired canonical ID retains status `RETIRED_SPLIT`; cannot be reused for new entities. | TEST_DESIGNED (Awaiting Phase 2) |

#### Detailed Specification of Canonical Membership Temporal Test Scenarios:
1. **TC-CAN-01a (Overlap Rejection & Backdated Conflict)**:
   - Given an existing membership with `valid_from = '2026-01-01T00:00:00.000000Z'` and `valid_to = '2026-06-01T00:00:00.000000Z'` (`status = 'USABLE'`).
   - Attempting to insert a second membership with `valid_from = '2026-05-15T00:00:00.000000Z'` and `valid_to = '2026-10-01T00:00:00.000000Z'` (`status = 'USABLE'`) raises `IntegrityError` (Postgres `excl_canonical_membership_no_overlap` or SQLite trigger `trg_prevent_membership_temporal_overlap_insert`).
   - Attempting to insert a backdated open membership with `valid_from = '2026-04-01T00:00:00.000000Z'` and `valid_to = NULL` also raises `IntegrityError`.
2. **TC-CAN-01c (Adjacent Endpoints Permitted)**:
   - Given existing membership with `valid_from = '2026-01-01T00:00:00.000000Z'` and `valid_to = '2026-06-01T00:00:00.000000Z'`.
   - Inserting a new membership with `valid_from = '2026-06-01T00:00:00.000000Z'` and `valid_to = NULL` succeeds because in half-open `[a, b)` intervals, point `'2026-06-01T00:00:00.000000Z'` is excluded from the first interval and included in the second.
3. **TC-CAN-01d (Degenerate Empty Interval Rejected)**:
   - Attempting to insert a membership with `valid_from = '2026-03-01T12:00:00.000000Z'` and `valid_to = '2026-03-01T12:00:00.000000Z'` fails database constraint `chk_temporal_validity` (`CHECK (valid_to IS NULL OR valid_to > valid_from)`).
4. **TC-CAN-01e (Lifecycle Transition via HELD and Adjudication)**:
   - When a data conflict or material attribute shift is detected, the membership is updated: `UPDATE canonical_memberships SET status = 'HELD' WHERE id = :id`.
   - Verify that the membership is immediately omitted from the active export crosswalk (`SELECT * FROM canonical_memberships WHERE status = 'USABLE'`).
   - Verify that while in `HELD`, it does not trigger GiST exclusion for pending exploratory assignments.
   - When Steward adjudicates as FALSE_ALARM: membership status is reverted to `USABLE`.
   - When Steward adjudicates as SPLIT/REASSIGN: existing membership is updated to `status = 'SUPERSEDED'`, `valid_to = NOW()`; and new canonical membership is created with `status = 'USABLE'`, `valid_from = NOW()`.
5. **TC-CAN-01g (Concurrency & Row-Level Serialization for Existing Membership)**:
   - Two concurrent database sessions Tx1 and Tx2 attempt to supersede membership for `source_record_id = X`.
   - Tx1 executes: `SELECT id FROM canonical_memberships WHERE source_record_id = :x AND status = 'USABLE' FOR UPDATE`.
   - Tx2 attempts the same query and blocks waiting for Tx1 lock release.
   - Tx1 performs update to `SUPERSEDED`, inserts new membership, and commits.
   - Tx2 unblocks, re-evaluates the `status = 'USABLE'` predicate, sees 0 rows matching, and cleanly aborts or raises a conflict exception without corrupting membership intervals.
6. **TC-CAN-01h (Concurrent Initial Insertion Exclusion on Clean Record)**:
   - Setup: A `source_record` has NO existing `USABLE` canonical membership.
   - Concurrent action: Two transactions Tx1 and Tx2 concurrently attempt to insert initial `USABLE` memberships for that same `source_record_id`:
     - Tx1 inserts: `valid_from = '2026-06-01T00:00:00.000000Z'`, `valid_to = NULL`, `status = 'USABLE'`, `canonical_entity_id = C1`.
     - Tx2 inserts: `valid_from = '2026-06-01T00:00:00.000000Z'`, `valid_to = NULL`, `status = 'USABLE'`, `canonical_entity_id = C2`.
   - Engine Enforcement:
     - On PostgreSQL: `EXCLUDE USING GIST` constraint on `(source_record_id, tstzrange)` detects the overlapping range at index commit; Tx2 raises `IntegrityError` (ExclusionViolation) and rolls back.
     - On SQLite: Using `BEGIN IMMEDIATE` / `EXCLUSIVE` transactions, SQLite serializes writers; trigger `trg_prevent_membership_temporal_overlap_insert` detects Tx1's interval and raises `RAISE(ABORT, 'Overlapping USABLE canonical membership interval detected for source record')`, forcing Tx2 to roll back.
   - Post-condition Verification:
     - Querying `SELECT COUNT(*) FROM canonical_memberships WHERE source_record_id = :id AND status = 'USABLE'` yields exactly 1.
     - Verifies that zero invalid overlapping states remain after transaction commit or rollback.

### 3.7. SQLite Timestamp Lexicographical Ordering Tests (`test_db_temporal_format.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-TIME-01 | `test_sqlite_iso8601_lexical_chronological_ordering` | SQLite text comparison on `YYYY-MM-DDTHH:MM:SS.ffffffZ` and SQLAlchemy `ISOUtcDateTime` TypeDecorator | Asserts that timestamps with identical dates and varying times/microseconds sort lexicographically in exact chronological order: `'2026-06-01T08:30:00.000000Z' < '2026-06-01T09:15:00.123456Z' < '2026-06-01T09:15:00.123457Z' < '2026-06-01T23:59:59.999999Z' < '9999-12-31T23:59:59.999999Z'`. Validates that space-separated timestamps are rejected by the TypeDecorator validator. | TEST_DESIGNED (Awaiting Phase 2) |

### 3.8. Audit, Governance & Export Tests (`test_db_audit_governance.py` & `test_db_export_manifest.py`)

| Test ID | Test Name | Target Constraint / Mechanism | Expected Assertion | Status |
|---|---|---|---|---|
| TC-AUD-01 | `test_audit_event_append_only` | `audit_events` hash chaining | Modifying prior record breaks cryptographic SHA-256 chain. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-EXP-01 | `test_export_excludes_held_and_unapproved` | Export query filtering `status = 'USABLE'` | Export manifest contains 0 unapproved candidate pairs and 0 `HELD` memberships. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-EXP-02 | `test_export_invalidation_on_split` | `export_manifest_items.is_superseded` | Post-export split flips `is_superseded = TRUE` on affected historical manifest items. | TEST_DESIGNED (Awaiting Phase 2) |
| TC-REC-01 | `test_deletion_ledger_restore_replay` | `deletion_ledger` application | Database restored from backup reapplies deletion ledger before opening query access. | TEST_DESIGNED (Awaiting Phase 2) |

---

## 4. Workload & Performance Benchmarking (Phase 5 Roadmap)

- `NFR-01 Full Batch Benchmark`: 15,000 records, up to 200,000 candidate pairs (SLA <= 60 mins). Status: `AWAITING_PHASE_5`.
- `NFR-02 Incremental Batch Benchmark`: 750 modified records against reference corpus (SLA <= 15 mins). Status: `AWAITING_PHASE_5`.
- `NFR-03 Workspace Query Latency`: 5 concurrent sessions, 200 operations (Lookup p95 <= 3s, Export 15k rows <= 60s). Status: `AWAITING_PHASE_5`.
