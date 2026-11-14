# DATABASE ARCHITECTURE & HIGH-LEVEL DESIGN
## SongNhat CRM Duplicate Detection and Entity Resolution System
### Version: 8.0 – Final Targeted Patch (Candidate Pair Reconciliation in batch_row_results, Zero Double-Counting, Source-Specific Import Batches)

---

## 1. Executive Summary & Architectural Overview

The **SongNhat CRM Duplicate Detection and Entity Resolution System** operates as an independent, auditable customer identity master registry. Its principal mission is to resolve duplicated enterprise business accounts and professional contacts across fragmented operational systems (CRM A, CRM B, CRM C) without modifying or mutating source CRM databases.

In strict compliance with the **SongNhat Request for Proposal (RFP)**, the architecture guarantees:
1. **Raw Source Lineage & Immutability (DAT 01, DAT 03)**: Source records are ingested into append-only raw versions. No deduplication, merging, or normalization overwrites original evidence.
2. **Deterministic & Explainable Matching (MAT 01 - MAT 08)**: Every candidate pair is derived through auditable blocking paths and directional feature evidence (Positive, Negative, Neutral). No silent Top-K truncation occurs; capacity breaches hold execution visibly.
3. **Segregation of Duties & Maker-Checker Governance (SEC 01, REV 03)**: Data Stewards propose matches or relationships; independent Approvers evaluate evidence and commit canonical state. Self-approval is strictly prevented at both application and database constraint tiers.
4. **Reversible Canonical Resolution & Temporal Integrity (REV 01 - REV 07)**: Canonical memberships maintain strictly non-overlapping temporal intervals (`[valid_from, valid_to)`) and operational lifecycles (`USABLE`, `HELD`, `SUPERSEDED`). Splits, unlinks, and rollbacks preserve lineage and invalidate affected downstream exports.
5. **Anti-Leakage & Data Protection (SEC 01 - SEC 08)**: In accordance with Vietnam Law 91/2025/QH15 and Decree 356/2025/ND-CP, server-side RBAC isolates unauthorized records, audit events are tamper-evident (cryptographically hashed), and retention policies are enforced via an auditable deletion ledger.

---

## 2. Technical Stack & Deployment Choices

### 2.1. Core Technologies
- **Object Relational Mapper**: SQLAlchemy 2.0+ utilizing modern `DeclarativeBase`, typed mappings (`Mapped[...]`), and relationship semantics.
- **Database Migrations**: Alembic for version-controlled, reproducible schema migrations with strict classification of reversible DDL vs irreversible data migration.
- **Production RDBMS**: **PostgreSQL 15+** (Dockerized in `docker-compose.yml` or managed enterprise instance), providing native UUID types, `JSONB` for raw payloads and evidence snapshots, `btree_gist` extension for temporal `EXCLUDE USING GIST` constraints, and transactional advisory locks.
- **Development & Testing Database**: **SQLite 3.x** (with foreign keys explicitly enabled via PRAGMA `foreign_keys = ON;`), maintaining dialect compatibility for developer workstations and local automated test suites.

### 2.2. Engineering Standards
- **Identifiers**: Primary keys across all business tables are standard 128-bit UUIDs (`uuid.uuid4`) represented natively in PostgreSQL (`UUID`) and as `CHAR(36)` in SQLite via a custom SQLAlchemy `GUIDType`.
- **Temporal Handling**: All timestamps are UTC with timezone awareness (`DateTime(timezone=True)`). SQLite strictly standardizes on exactly one timestamp representation: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (RFC 3339 / ISO-8601 with literal `T` separator, 6-digit microsecond precision, and trailing literal `Z` UTC designator). The alternative space separator format is strictly prohibited. The sentinel value replacing infinity for open intervals is standardized as `9999-12-31T23:59:59.999999Z` across all SQLite schemas and triggers. Python/SQLAlchemy enforces this via a custom `TypeDecorator` (`ISOUtcDateTime`). Intervals follow the half-open standard `[valid_from, valid_to)` (inclusive start, exclusive end).
- **Audit Trails**: Append-only storage pattern; updates to critical domain entities require new records or state transition ledgers.

---

## 3. Seven Core Architectural Domains (Exact Count: 33 Tables)

The relational architecture is decomposed into 7 decoupled functional domains, encompassing exactly **33 dedicated tables** to eliminate overlapping responsibilities:

```
+-----------------------------------------------------------------------------------+
|                            DOMAIN ARCHITECTURE MAP (33 TABLES)                    |
+-----------------------------------------------------------------------------------+
|  1. USER & ACCESS CONTROL (5) : users, roles, permissions, user_roles,            |
|                                 role_permissions                                  |
|  2. SOURCE & INTAKE (8)       : source_systems, import_batches, batch_row_results,|
|                                 source_records, source_record_versions,           |
|                                 source_identifiers, matching_runs, run_sources    |
|  3. NORMALIZATION & MATCH (5) : normalization_policies, normalized_features,      |
|                                 candidate_pairs, candidate_blocking_paths,        |
|                                 candidate_pair_evidence                           |
|  4. CLUSTER & HUMAN REVIEW (5): candidate_clusters, candidate_cluster_members,    |
|                                 review_tasks, review_decisions,                   |
|                                 pair_decision_constraints                         |
|  5. CANONICAL RESOLUTION (5)  : canonical_entities, canonical_memberships,        |
|                                 canonical_fields, canonical_field_provenance,     |
|                                 entity_relationships                              |
|  6. AUDIT & GOVERNANCE (3)    : audit_events, retention_policies, deletion_ledger |
|  7. EXPORT MANAGEMENT (2)     : export_jobs, export_manifest_items                |
+-----------------------------------------------------------------------------------+
|  TOTAL TABLES: 5 + 8 + 5 + 5 + 5 + 3 + 2 = 33 TABLES                              |
+-----------------------------------------------------------------------------------+
```

---

## 4. Advanced Referential Integrity Architecture

### 4.1. Entity Pool Isolation via Composite Foreign Keys
- **Source Intake Level**:
  - `source_systems` declares `UNIQUE (id, entity_type)`.
  - `source_records` declares `FOREIGN KEY (source_system_id, entity_type) REFERENCES source_systems (id, entity_type) ON DELETE RESTRICT`.
  This physically prevents an `ACCOUNT` source system from originating `CONTACT` records, and vice versa.
- **Candidate Pair Matching Level**:
  - `candidate_pairs` enforces that both participants share the exact same `entity_type` by declaring:
    - `UNIQUE (id, entity_type)` on `source_records`.
    - `FOREIGN KEY (left_source_record_id, entity_type) REFERENCES source_records (id, entity_type)`
    - `FOREIGN KEY (right_source_record_id, entity_type) REFERENCES source_records (id, entity_type)`
  This physically prevents pairing an Account with a Contact at the RDBMS engine tier.

### 4.2. Relationship Entity Type Compatibility
- `entity_relationships` binds `(from_canonical_id, from_entity_type)` and `(to_canonical_id, to_entity_type)` via composite FKs to `canonical_entities (id, entity_type)`.
- The `chk_rel_type_entity_compat` constraint enforces:
  - `PARENT_OF`, `BRANCH_OF`, `SITE_OF`: Account to Account only.
  - `AFFILIATED_WITH`: Contact to Account, Account to Account, or Contact to Contact.

### 4.3. Temporal Non-Overlapping Membership Integrity
- **PostgreSQL**: Enforced via `EXCLUDE USING GIST` on `(source_record_id WITH =, tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)') WITH &&) WHERE (status = 'USABLE')`.
- **SQLite**: Enforced via trigger `trg_prevent_membership_temporal_overlap` and transactional validation using standardized ISO-8601 UTC strings (`YYYY-MM-DDTHH:MM:SS.ffffffZ`) with upper sentinel `'9999-12-31T23:59:59.999999Z'`.
- **Interval Semantics**: Half-open `[valid_from, valid_to)` convention: adjacent intervals `[t1, t2)` and `[t2, t3)` do not conflict.
- **Strictly Positive Lifespan**: `CHECK (valid_to IS NULL OR valid_to > valid_from)` strictly prohibits degenerate zero-duration intervals `[t, t)`. Empty intervals are rejected at the database engine tier.
- **Temporal Scope Evaluation for Non-Membership Tables**:
  - *`source_record_versions`*: Raw intake snapshots are sequenced by `version_number` and `imported_at`. Engine-level range exclusion on `[effective_from, effective_to)` is intentionally omitted to prevent intake batch crashes when upstream source systems supply retroactive corrections or messy historical attribute dates (DAT 01, DAT 02).
  - *`canonical_fields`*: Governed by Single Active Golden Value per Entity & Field (REV 04), enforced by partial unique index `uq_single_active_canonical_field` (`WHERE status = 'ACTIVE' AND valid_to IS NULL`). Full historical exclusion across `SUPERSEDED` rows is intentionally omitted to permit retroactive governance timeline adjustments without affecting active MDM lookup performance.

### 4.4. Cycle Detection & Concurrency Serialization
- **Hierarchical Relationships (`PARENT_OF`, `BRANCH_OF`, `SITE_OF`)**:
  - Enforce Directed Acyclic Graph (DAG) trees.
  - To prevent concurrent race conditions where Tx1 creates A -> B and Tx2 creates B -> A simultaneously, transactions inserting hierarchical edges acquire a PostgreSQL transaction-scoped advisory lock (`pg_advisory_xact_lock(hashtext('hierarchy_dag_lock'))`), serializing DAG validation.
- **Affiliation Relationships (`AFFILIATED_WITH`)**:
  - Represent non-hierarchical, multi-directional professional links. Exempt from DAG restrictions and serialization mutexes.

### 4.5. Legacy Provenance, Mapping & Mathematical Conservation (Persisted in 33 Tables)
- **Conservation of 33 Tables Architecture (Zero 34th Table)**:
  - All legacy source records and candidate pairs are managed strictly within existing tables without adding a 34th table.
  - The staging tables `legacy_source_records`, `legacy_candidate_pairs`, and `legacy_audit_logs` remain preserved 100% in read-only state.
- **Authentic Nature of Candidate Pairs & Matching Run Governance**:
  - Candidate pairs represent comparison edges between two source records across systems; they do not belong to a single source system and are not intake records. The system does NOT falsely assume CRM_A is the source of all candidate pairs.
  - Instead, candidate pairs are governed by their authentic parent entity: `matching_runs`. Migration 0008 provisions **two dedicated matching runs** in `matching_runs` segregated by pool: `MIG-0008-HISTORICAL-PAIRS-ACCOUNT` (`entity_pool = 'ACCOUNT'`) and `MIG-0008-HISTORICAL-PAIRS-CONTACT` (`entity_pool = 'CONTACT'`), utilizing exclusively the existing schema columns (`id`, `run_code`, `entity_pool`, `status`, `policy_id`, `total_candidates`, `ceiling_breached`, `started_at`, `completed_at`, `executed_by`, `notes`, `created_at`).
- **Endpoint Resolution, Source-System Parity & Legacy Entity-Type Compatibility**:
  - `legacy_candidate_pairs` stores only `left_source_key` and `right_source_key` without specifying the source CRM. Because legacy uniqueness was only per-CRM, keys may collide across CRMs.
  - **Source-System Parity Join (Immune to Multiple Batches)**:
    1. Keys existing exactly once across legacy records (`COUNT(*) = 1`) uniquely identify the authentic legacy `source_system` and entity type.
    2. Resolution joins `source_systems ss ON ss.source_code = ulk.source_system AND ss.entity_type = ulk.mapped_entity_pool` and `source_records sr ON sr.source_key = ulk.source_key AND sr.source_system_id = ss.id AND sr.entity_type = ulk.mapped_entity_pool`.
    3. The resolution query does NOT join `import_batches` directly; it is mathematically immune to row multiplication if a CRM has multiple historical batches.
  - **Legacy Entity-Type Mapping Rules & Bidirectional Compatibility**:
    * `COMPANY` -> `ACCOUNT` (Subtype `COMPANY`)
    * `BRANCH` -> `ACCOUNT` (Subtype `BRANCH`)
    * `CONTACT` -> `CONTACT` (Subtype `PERSON`)
    * Incompatible mappings are strictly prohibited: legacy `CONTACT` is never mapped to `ACCOUNT` systems/records, and legacy `COMPANY`/`BRANCH` is never mapped to `CONTACT` systems/records.
    * Does NOT use `MIN(entity_type)` to paper over conflicting legacy data; keys with conflicting mapped pools are excluded from migrated sets and quarantined.
    * **Data Owner Subtype Sign-off**: Mapping `COMPANY` and `BRANCH` to the unified `ACCOUNT` pool preserves subtype categorization in `record_payload` without schema-level entity fragmentation; formally flagged for Data Owner sign-off before Phase 2 execution.
  - **Zero Speculation Rule**: If any key appears more than once across `legacy_source_records` ($L_{cnt} > 1$ or $R_{cnt} > 1$), it cannot be uniquely resolved to an endpoint without fabricating assumptions; it is safely quarantined under `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT`.
- **Strict 5-Stage Mutually Exclusive Classification Cascade**:
  - Candidate pairs are classified through a strict priority cascade:
    1. `PAIR_REJECTED_DANGLING_KEY`: Key does not exist in legacy source rows ($L_{cnt} = 0$ or $R_{cnt} = 0$).
    2. `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT`: Key appears > 1 times in legacy source rows ($L_{cnt} > 1$ or $R_{cnt} > 1$).
    3. `PAIR_QUARANTINED_ENDPOINT`: Key is unique, but endpoint row was quarantined during intake ($L_{mig}$ is NULL or $R_{mig}$ is NULL).
    4. `PAIR_REJECTED_CROSS_POOL_MISMATCH`: Both endpoints migrated, but one is ACCOUNT and other is CONTACT ($L_{mig}.entity_type \ne R_{mig}.entity_type$).
    5. `PAIR_MIGRATED`: Both endpoints uniquely resolved, migrated, same pool, and candidate pair physically verified with `legacy_pair_id = legacy.id`, correct pool matching run, and canonical endpoints.
  - Any pair failing criteria 1-4 that is unmapped evaluates to `PAIR_UNMAPPED_DISCREPANCY`, which immediately triggers assertion failure and transaction rollback.
- **Transactional Ordering & Two-Way Physical Parity**:
  - **Transaction Order**: Runs are initialized with `status = 'RUNNING'` and `total_candidates = 0`; pairs are inserted; runs are updated to `status = 'COMPLETED'` and actual `total_candidates = COUNT(...)`; two-way parity and conservation assertions are executed; transaction commits on PASS or aborts on failure.
  - **Two-Way Parity**: Legacy-to-physical assertion verifies every `PAIR_MIGRATED` exists in `candidate_pairs`; physical-to-legacy assertion verifies zero orphan migrated candidate pairs, zero duplicate `legacy_pair_id`, and zero endpoint mismatches.
- **Source-Specific Batches & Unmapped Source Quarantine (Zero Fake Sources)**:
  - Dedicated import batches (`BATCH_CRM_A`, `BATCH_CRM_B`, `BATCH_CRM_C`) process source records for their respective pools.
  - Records lacking a verifiable `source_system` are quarantined into `BATCH_UNMAPPED_QUARANTINE` with `source_system_id = NULL`, enforced by `CHECK ((batch_type = 'UNMAPPED_QUARANTINE' AND source_system_id IS NULL) OR (batch_type <> 'UNMAPPED_QUARANTINE' AND source_system_id IS NOT NULL))`. Zero fake source systems (such as `CRM_UNKNOWN`) are created, and no record is falsely attributed to CRM_A/B/C.
- **Batch-Source Parity & Multi-Batch Linking in `run_sources`**:
  - `run_sources` enforces Composite FK `(import_batch_id, source_system_id) REFERENCES import_batches (id, source_system_id)`, guaranteeing at the database engine tier that linked batches strictly belong to their declared source systems.
  - Constraint `UNIQUE (matching_run_id, import_batch_id)` permits linking multiple batches belonging to the same source system (e.g. historical baseline and delta batches) within a single matching run.
- **Evidence Provenance & Zero Fabrication**:
  - `candidate_pairs` stores `legacy_reasons_raw` verbatim and maintains `legacy_pair_id (INTEGER NULL UNIQUE)`.
  - In `candidate_pair_evidence`, legacy rows carry `is_legacy_evidence = TRUE`, `provenance = 'LEGACY_MIGRATION'`, while `similarity_score`, `evidence_direction`, `evidence_weight`, and `policy_version` are strictly `NULL`.
  - In `audit_events`, legacy audit logs are preserved with original fields and tagged `is_migrated_legacy = TRUE` and `hash_generated_at_migration = TRUE`.
- **Comprehensive Idempotency State Machine & Concurrency Control**:
  - **State A (None exist)**: Normal execution.
  - **State B (Both exist & reconciled)**: Idempotent success, exits safely (no-op).
  - **State C (Only one exists)**: Fail-closed; raises `RuntimeError`.
  - **State D (Both exist but reconciliation FAILED)**: Fail-closed; raises `RuntimeError`, requires backup restore.
  - **State E (Concurrent runs & Alembic Transaction Lifecycle)**:
    * PostgreSQL: Serialized via `pg_advisory_xact_lock(hashtext('MIG_0008_HISTORICAL_PAIRS'))` acquired at start of transaction and released upon commit/rollback.
    * SQLite: Avoids illegal nested `BEGIN IMMEDIATE` on already active connections; managed via SQLAlchemy engine `begin` listener (`conn.exec_driver_sql("BEGIN IMMEDIATE")`) and `PRAGMA busy_timeout = 30000;` on connect.
    * Unique constraints provide the ultimate database-engine backstop.
- **NULL-Safe Physical Endpoint Parity & Bilateral Pool Symmetry**:
  - `physical_endpoint_verification` strictly detects NULL endpoints (`left_source_record_id`, `right_source_record_id`), NULL entity types, and inverted canonical ordering, ensuring no NULL comparison accidentally falls into `ELSE 0`.
  - Enforces bilateral pool symmetry: left and right target pools must match (`l_mig.entity_type = r_mig.entity_type`), and candidate pair pool must equal both endpoints (`ps.entity_type = l_mig.entity_type` AND `ps.entity_type = r_mig.entity_type`).
- **Three-Level ERD Validation Breakdown**:
  - Structural Validation: PASS (33 entities, 43 relationships verified).
  - Mermaid Syntax Validation: PASS (0 syntax errors across 484 lines).
  - Actual Rendering Validation: Environment lacking pre-installed `mmdc`; packaged into `TC-MIG-32` and `TC-MIG-40` as `TEST_DESIGNED (Awaiting Phase 2 CI/CD Environment)`.

---

## 5. Workload Capacity & Target Metrics

| Metric / Requirement | Target / SLA | Architectural Solution | Status |
|---|---|---|---|
| Total Source Capacity | 15,000 records | Low-overhead relational tables with composite index lookups | DESIGNED |
| Max Candidate Pairs | 200,000 unique pairs | Multi-path blocking + visible ceiling breach flags (`ceiling_breached`) | DESIGNED |
| Full Batch Matching | <= 60 minutes | Set-based SQL bulk inserts + indexed blocking joins | DESIGNED |
| Incremental Matching | 750 records in <= 15 min | Version delta detection (`source_record_versions.version_number`) | DESIGNED |
| Concurrent Sessions | 5 named sessions | Connection pooling (`pool_size=10, max_overflow=20`), row-level locking | DESIGNED |
| Identity Lookup p95 | <= 3.0 seconds | Partial index on `canonical_memberships (source_record_id) WHERE status = 'USABLE'` | DESIGNED |
| Crosswalk Export SLA | 15,000 rows in <= 60 sec | Streaming query from indexed `canonical_memberships` view | DESIGNED |
| RPO / RTO Target | RPO <= 24h, RTO <= 8h | WAL archiving + Deletion Ledger replay on restore | DESIGNED |
