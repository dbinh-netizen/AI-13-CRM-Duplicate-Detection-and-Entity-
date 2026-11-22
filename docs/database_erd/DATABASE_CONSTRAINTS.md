# DATABASE CONSTRAINTS & INDEXING STRATEGY (33 TABLES)
## SongNhat CRM Duplicate Detection and Entity Resolution System
### Version: 8.1 – Final Targeted Patch (Matching Runs Schema Alignment, Run Sources Parity, Unmapped Quarantine)

---

## 1. Primary Keys & Identifier Strategy

All tables throughout the architecture use 128-bit Universally Unique Identifiers (UUIDv4) as primary keys:
- **PostgreSQL**: Native `UUID` column type with `DEFAULT gen_random_uuid()` or application-generated `uuid.uuid4()`.
- **SQLite (Development / Testing)**: `CHAR(36)` stored as hyphenated string format via a custom SQLAlchemy `GUIDType`.
- **Business Rationale**: Eliminates sequential ID exposure, prevents primary key collisions during distributed processing, and cleanly separates internal operational IDs from external source CRM keys.

---

## 2. Integrity & Check Constraints Matrix

| Domain | Table | Constraint Name | Constraint Type | Definition / Expression | Business Rule Enforced |
|---|---|---|---|---|---|
| Access | `users` | `uq_users_username` | UNIQUE | `(username)` | Prevents duplicate usernames. |
| Access | `users` | `uq_users_email` | UNIQUE | `(email)` | Prevents duplicate employee emails. |
| Access | `roles` | `uq_roles_role_code` | UNIQUE | `(role_code)` | Standardizes role enumeration. |
| Access | `permissions` | `uq_permissions_code` | UNIQUE | `(permission_code)` | Standardizes permission codes. |
| Source | `source_systems` | `uq_source_code` | UNIQUE | `(source_code)` | Uniquely identifies CRM A, CRM B, CRM C. |
| Source | `source_systems` | `uq_source_sys_id_type` | UNIQUE | `(id, entity_type)` | Prerequisite key for composite FK intake pool isolation. |
| Source | `import_batches` | `ck_import_batch_source_mapping` | CHECK | `(batch_type = 'UNMAPPED_QUARANTINE' AND source_system_id IS NULL) OR (batch_type <> 'UNMAPPED_QUARANTINE' AND source_system_id IS NOT NULL)` | Operational batches require authentic source system; quarantine batch permits NULL without fabricating fake source. |
| Source | `import_batches` | `uq_import_batch_system` | UNIQUE | `(id, source_system_id)` | Prerequisite key for composite FK verifying batch-source parity. |
| Source | `batch_row_results` | `uq_batch_row_num` | UNIQUE | `(import_batch_id, row_number)` | Enforces exactly 1 evaluation row per intake row per batch (Zero Double-Counting). |
| Source | `source_records` | `fk_source_rec_system_pool` | FOREIGN KEY | `(source_system_id, entity_type) REFERENCES source_systems(id, entity_type)` | Prevents ACCOUNT sources from receiving CONTACT records and vice versa. |
| Source | `source_records` | `uq_source_entity_key` | UNIQUE | `(source_system_id, entity_type, source_key)` | Ensures immutable record anchor uniqueness per source. |
| Source | `source_records` | `uq_source_rec_id_type` | UNIQUE | `(id, entity_type)` | Prerequisite key for composite FK pool enforcement. |
| Source | `source_record_versions` | `uq_source_rec_version` | UNIQUE | `(source_record_id, version_number)` | Sequential versioning; prevents payload overwrites. |
| Source | `source_record_versions` | `uq_srv_id_rec_id` | UNIQUE | `(id, source_record_id)` | Prerequisite key for composite FK version binding. |
| Source | `run_sources` | `fk_run_sources_batch_system` | FOREIGN KEY | `(import_batch_id, source_system_id) REFERENCES import_batches(id, source_system_id)` | **Batch-Source Parity Composite FK**: Guarantees at database engine tier that batch strictly belongs to declared source system. |
| Source | `run_sources` | `uq_run_source_batch` | UNIQUE | `(matching_run_id, import_batch_id)` | Prevents duplicate inclusion of same batch in one run, while **allowing multiple batches from same source system**. |
| Matching | `normalization_policies` | `uq_policy_version` | UNIQUE | `(policy_name, version)` | Ensures reproducible policy version tracking. |
| Matching | `candidate_pairs` | `chk_cand_pair_order` | CHECK | `left_source_record_id < right_source_record_id` | **Canonical pair ordering**: prevents duplicate inverted edges `(A, B)` vs `(B, A)`. |
| Matching | `candidate_pairs` | `uq_cand_pair_run` | UNIQUE | `(matching_run_id, left_source_record_id, right_source_record_id)` | Exactly one candidate pair per record combination per run. |
| Matching | `candidate_pairs` | `uq_cand_pair_legacy_id` | UNIQUE | `(legacy_pair_id)` | Enforces strict 1:1 anchor between legacy pair and migrated candidate pair. |
| Matching | `candidate_pairs` | `chk_cand_score_range`| CHECK | `total_score >= 0.00 AND total_score <= 100.00` | Bounds similarity score. |
| Matching | `candidate_pair_evidence`| `chk_evidence_dir` | CHECK | `(is_legacy_evidence = TRUE OR (evidence_direction IS NOT NULL AND evidence_direction IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')))` | Standardizes directional evidence classification; allows NULL for legacy evidence. |
| Matching | `candidate_pair_evidence`| `chk_evidence_fields`| CHECK | `(is_legacy_evidence = TRUE OR (evidence_weight IS NOT NULL AND policy_version IS NOT NULL))` | Requires weight and policy for modern engine evidence; allows NULL for legacy migration. |
| Cluster | `candidate_clusters` | `uq_cluster_id_type` | UNIQUE | `(id, entity_type)` | Prerequisite key for cluster member composite FK. |
| Cluster | `candidate_cluster_members` | `uq_cluster_member` | UNIQUE | `(candidate_cluster_id, source_record_id)` | Prevents duplicate enrollment in same cluster. |
| Review | `review_tasks` | `chk_task_target_exclusivity` | CHECK | `((task_type = 'PAIR_REVIEW' AND candidate_pair_id IS NOT NULL AND candidate_cluster_id IS NULL) OR (task_type IN ('CLUSTER_REVIEW', 'SPLIT_ADJUDICATION') AND candidate_cluster_id IS NOT NULL AND candidate_pair_id IS NULL))` | **Strict Target Exclusivity**: Pair review cannot hold cluster ID; Cluster/Split review cannot hold pair ID. |
| Review | `review_decisions` | `chk_no_self_approval`| CHECK | `approved_by IS NULL OR proposed_by <> approved_by` | **Strict Maker-Checker**: Data Steward cannot approve their own proposal. |
| Review | `review_decisions` | `uq_dec_id_approver` | UNIQUE | `(id, approved_by)` | Prerequisite key for composite FK approver consistency. |
| Constraints| `pair_decision_constraints`| `chk_constraint_order`| CHECK | `left_source_record_id < right_source_record_id` | Enforces standard node ordering for pairwise negative constraints. |
| Canonical | `canonical_entities` | `uq_canonical_code` | UNIQUE | `(canonical_code)` | Guarantees uniqueness of persistent Canonical ID. |
| Canonical | `canonical_entities` | `uq_can_id_type` | UNIQUE | `(id, entity_type)` | Prerequisite key for canonical membership & relationship composite FKs. |
| Canonical | `canonical_memberships`| `chk_membership_status`| CHECK | `status IN ('USABLE', 'HELD', 'SUPERSEDED')` | Strict membership operational lifecycle. |
| Canonical | `canonical_memberships`| `chk_temporal_validity`| CHECK | `valid_to IS NULL OR valid_to > valid_from` | Enforces strictly positive interval lifespan; rejects degenerate empty intervals [t, t). |
| Canonical | `canonical_fields`     | `chk_can_field_temporal`| CHECK | `valid_to IS NULL OR valid_to > valid_from` | Enforces strictly positive lifespan for canonical field values. |
| Hierarchy | `entity_relationships` | `chk_rel_temporal`      | CHECK | `valid_to IS NULL OR valid_to > valid_from` | Enforces strictly positive lifespan for entity relationship links. |
| Hierarchy | `entity_relationships` | `chk_rel_no_self_loop` | CHECK | `from_canonical_id <> to_canonical_id` | Prevents circular self-referencing 1-hop relationship loops. |
| Hierarchy | `entity_relationships` | `chk_rel_type_entity_compat` | CHECK | `((relationship_type IN ('PARENT_OF', 'BRANCH_OF', 'SITE_OF') AND from_entity_type = 'ACCOUNT' AND to_entity_type = 'ACCOUNT') OR (relationship_type = 'AFFILIATED_WITH' AND ((from_entity_type = 'CONTACT' AND to_entity_type = 'ACCOUNT') OR (from_entity_type = 'ACCOUNT' AND to_entity_type = 'ACCOUNT') OR (from_entity_type = 'CONTACT' AND to_entity_type = 'CONTACT'))))` | **Strict Relationship Entity Type Compatibility**: Enforces valid entity pairs per relationship type. |
| Export | `export_manifest_items` | `uq_export_source_rec` | UNIQUE | `(export_job_id, source_record_id)` | One mapping entry per source record per published export. |

---

## 3. Cross-Table Integrity: Composite Foreign Keys

### 3.1. Entity Pool Isolation (Account vs Contact)
- **Source Intake Level**:
  - `source_systems` declares `UNIQUE (id, entity_type)`.
  - `source_records` binds `(source_system_id, entity_type)` via composite FK:
    ```sql
    ALTER TABLE source_systems
      ADD CONSTRAINT uq_source_sys_id_type UNIQUE (id, entity_type);

    ALTER TABLE source_records
      ADD CONSTRAINT fk_source_rec_system_pool
      FOREIGN KEY (source_system_id, entity_type)
      REFERENCES source_systems (id, entity_type) ON DELETE RESTRICT;
    ```
    *Result*: Physically impossible for an `ACCOUNT` source system to ingest `CONTACT` records, or for a `CONTACT` source system to ingest `ACCOUNT` records.

- **Candidate Pair Matching Level**:
  - `source_records` declares `UNIQUE (id, entity_type)`.
  - `candidate_pairs` stores `entity_type` alongside `left_source_record_id` and `right_source_record_id`.
  - Composite Foreign Keys:
    ```sql
    ALTER TABLE candidate_pairs
      ADD CONSTRAINT fk_cand_pair_left_pool
      FOREIGN KEY (left_source_record_id, entity_type)
      REFERENCES source_records (id, entity_type) ON DELETE RESTRICT;

    ALTER TABLE candidate_pairs
      ADD CONSTRAINT fk_cand_pair_right_pool
      FOREIGN KEY (right_source_record_id, entity_type)
      REFERENCES source_records (id, entity_type) ON DELETE RESTRICT;
    ```
    *Result*: Physically impossible for a pair to connect an Account to a Contact.

### 3.2. Entity Relationship Type Compatibility
- `canonical_entities` declares `UNIQUE (id, entity_type)`.
- `entity_relationships` declares `from_entity_type` and `to_entity_type` with composite FKs:
  ```sql
  FOREIGN KEY (from_canonical_id, from_entity_type) REFERENCES canonical_entities (id, entity_type);
  FOREIGN KEY (to_canonical_id, to_entity_type) REFERENCES canonical_entities (id, entity_type);
  ```
  Combined with `chk_rel_type_entity_compat`, this prevents assigning `PARENT_OF` or `BRANCH_OF` to Contact entities at the database engine level.

### 3.3. Batch and Source System Parity (`run_sources`)
- `import_batches` declares `UNIQUE (id, source_system_id)`.
- `run_sources` binds `(import_batch_id, source_system_id)` via Composite FK:
  ```sql
  ALTER TABLE import_batches
    ADD CONSTRAINT uq_import_batch_system UNIQUE (id, source_system_id);

  ALTER TABLE run_sources
    ADD CONSTRAINT fk_run_sources_batch_system
    FOREIGN KEY (import_batch_id, source_system_id)
    REFERENCES import_batches (id, source_system_id) ON DELETE RESTRICT;
  ```
- *Result*: Physically guarantees at the database engine tier that a batch declared in `run_sources` strictly matches the authentic source system that owns it, completely eliminating cross-source misattribution while permitting a single run to incorporate multiple batches from the same source system.

### 3.4. Candidate Pair Legacy Anchor & Migration Idempotency Invariants
- **1:1 Legacy Anchor Invariant**:
  ```sql
  ALTER TABLE candidate_pairs
    ADD CONSTRAINT uq_cand_pair_legacy_id UNIQUE (legacy_pair_id);
  ```
  *Result*: Guarantees that each historical pair in `legacy_candidate_pairs` can be migrated at most once into `candidate_pairs`. Re-executing migration revision 0008 will never create duplicate pairs.
- **Run Identification Invariant**:
  ```sql
  ALTER TABLE matching_runs
    ADD CONSTRAINT uq_matching_runs_code UNIQUE (run_code);
  ```
  *Result*: Blocks duplicate creation of historical runs `MIG-0008-HISTORICAL-PAIRS-ACCOUNT` and `MIG-0008-HISTORICAL-PAIRS-CONTACT`.
- **Intra-Run Endpoint Uniqueness**:
  ```sql
  ALTER TABLE candidate_pairs
    ADD CONSTRAINT uq_cand_pair_run UNIQUE (matching_run_id, left_source_record_id, right_source_record_id);
  ```
- **Two-Way Parity & Mathematical Conservation Rule**:
  - Legacy-to-Physical: Every legacy pair classified as `PAIR_MIGRATED` must uniquely exist in `candidate_pairs` with matching endpoints, pool, and `legacy_pair_id`.
  - Physical-to-Legacy: Every physical `candidate_pairs` row created by migration 0008 (`is_migrated_legacy = TRUE`) must originate from a valid row in `legacy_candidate_pairs` (zero orphan pairs, zero duplicate `legacy_pair_id`, and zero endpoint mismatches).
  - Total Conservation: $\text{Total Legacy Pairs} = \text{Evaluated Pairs} = \sum \text{5 Mutually Exclusive Outcomes}$.
  - Discrepancy Strictness: Any `PAIR_UNMAPPED_DISCREPANCY` causes immediate assertion failure and transaction rollback.
- **Source-System Endpoint Parity & Legacy Entity-Type Compatibility**:
  - Resolving legacy endpoints to `source_records` strictly enforces matching `source_systems.source_code = legacy_source_records.source_system`, matching entity pool, and `UNIQUE (source_system_id, entity_type, source_key)`.
  - Enforces deterministic mapping: `COMPANY -> ACCOUNT`, `BRANCH -> ACCOUNT`, `CONTACT -> CONTACT`. Conflicting legacy keys are quarantined; `MIN(entity_type)` is never used to paper over data inconsistencies.
  - Subtype distinction (`COMPANY` vs `BRANCH`) is preserved in `record_payload` without entity pool fragmentation (subject to formal Data Owner sign-off).
  - Independent of `import_batches` row multiplicity; immune to multi-batch intake scenarios.
- **NULL-Safe Physical Endpoint Parity & Bilateral Pool Symmetry**:
  - Verification assertions strictly detect NULL endpoints, NULL entity types, and inverted canonical ordering, guaranteeing that three-valued logic (3VL) NULL evaluations do NOT fall into false PASS (`ELSE 0`).
  - Asserts bilateral pool symmetry: left and right endpoints must belong to the identical entity pool (`l_mig.entity_type = r_mig.entity_type`), and candidate pair pool must match both endpoints (`ps.entity_type = l_mig.entity_type` AND `ps.entity_type = r_mig.entity_type`).
- **Alembic Transaction Locking Lifecycle**:
  - PostgreSQL: `pg_advisory_xact_lock` guarantees mutual exclusion across concurrent workers, held for the entire transaction lifecycle and released upon COMMIT/ROLLBACK.
  - SQLite: Serialized via SQLAlchemy engine `begin` listener (`conn.exec_driver_sql("BEGIN IMMEDIATE")`) and `PRAGMA busy_timeout = 30000;` on connect, prohibiting illegal nested `BEGIN IMMEDIATE` commands on active SQLAlchemy connections.

---

## 4. Temporal Non-Overlapping Membership Integrity (Blocker 2 Resolution)

### 4.1. Definition of Temporal Interval Convention
The system standardizes on **half-open temporal intervals**: `[valid_from, valid_to)` (inclusive start timestamp, exclusive end timestamp).
- **Strictly Positive Lifespan**: Intervals must satisfy `CHECK (valid_to IS NULL OR valid_to > valid_from)`. Degenerate empty intervals `[t, t)` where `valid_to == valid_from` contain zero points and are strictly prohibited across all temporal tables (`canonical_memberships`, `canonical_fields`, `entity_relationships`).
- **Adjacent intervals do NOT overlap**: An interval ending at `'2026-06-01T00:00:00.000000Z'` and a new interval starting at `'2026-06-01T00:00:00.000000Z'` touch at an instantaneous boundary without intersection. In half-open semantics `[start, end)`, point `'2026-06-01T00:00:00.000000Z'` belongs exclusively to the second interval.
- **Open intervals**: When `valid_to IS NULL`, the interval is treated as extending to infinity: `[valid_from, infinity)`.
- **SQLite Exactly-One ISO-8601 UTC Timestamp Representation**: Because SQLite evaluates `<`, `>`, `<=`, `>=` on `TEXT` columns using ASCII lexicographical sorting, all timestamps stored in SQLite MUST adhere strictly to exactly one string representation: `YYYY-MM-DDTHH:MM:SS.ffffffZ` (literal `T` separator, 6-digit microsecond precision, literal trailing `Z` UTC zone indicator). The alternative space separator format is strictly prohibited. The application data access layer enforces this via SQLAlchemy `TypeDecorator` (`ISOUtcDateTime`). The open-interval upper sentinel in SQLite triggers is standardized as `'9999-12-31T23:59:59.999999Z'`, which chronologically and lexicographically exceeds any operational CRM timestamp.

### 4.2. PostgreSQL Implementation: `EXCLUDE USING GIST`
PostgreSQL enforces non-overlapping temporal intervals via the `btree_gist` extension and range types (`tstzrange`):
```sql
CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE canonical_memberships
ADD CONSTRAINT excl_canonical_membership_no_overlap
EXCLUDE USING GIST (
    source_record_id WITH =,
    tstzrange(valid_from, COALESCE(valid_to, 'infinity'::timestamptz), '[)') WITH &&
)
WHERE (status = 'USABLE');
```
*Effect*: The PostgreSQL storage engine physically blocks any transaction attempting to insert or update a `USABLE` membership whose `[valid_from, valid_to)` interval overlaps with an existing `USABLE` membership for the same `source_record_id`.

### 4.3. SQLite Implementation: Database Triggers & Transaction Guard
Since SQLite lacks native GiST range indexes, temporal non-overlap is guaranteed via dual database triggers operating on standardized `YYYY-MM-DDTHH:MM:SS.ffffffZ` UTC timestamps:
```sql
CREATE TRIGGER trg_prevent_membership_temporal_overlap_insert
BEFORE INSERT ON canonical_memberships
WHEN NEW.status = 'USABLE'
BEGIN
  SELECT RAISE(ABORT, 'Overlapping USABLE canonical membership interval detected for source record')
  WHERE EXISTS (
    SELECT 1 FROM canonical_memberships
    WHERE source_record_id = NEW.source_record_id
      AND status = 'USABLE'
      AND (NEW.valid_from < COALESCE(valid_to, '9999-12-31T23:59:59.999999Z')
           AND COALESCE(NEW.valid_to, '9999-12-31T23:59:59.999999Z') > valid_from)
  );
END;

CREATE TRIGGER trg_prevent_membership_temporal_overlap_update
BEFORE UPDATE ON canonical_memberships
WHEN NEW.status = 'USABLE'
BEGIN
  SELECT RAISE(ABORT, 'Overlapping USABLE canonical membership interval detected for source record')
  WHERE EXISTS (
    SELECT 1 FROM canonical_memberships
    WHERE source_record_id = NEW.source_record_id
      AND id <> NEW.id
      AND status = 'USABLE'
      AND (NEW.valid_from < COALESCE(valid_to, '9999-12-31T23:59:59.999999Z')
           AND COALESCE(NEW.valid_to, '9999-12-31T23:59:59.999999Z') > valid_from)
  );
END;
```

### 4.4. Temporal Integrity Evaluation for Non-Membership Domains

#### A. Source Record Versions (`source_record_versions`)
- **Evaluation Question**: Is a temporal exclusion constraint (`EXCLUDE USING GIST`) required for `[effective_from, effective_to)` across versions of the same `source_record_id`?
- **Decision: NO Engine-Level Exclusion Constraint**.
- **Business & Architectural Rationale**:
  1. `source_record_versions` is an immutable raw intake snapshot table (DAT 01, DAT 02). Its lineage is monotonically ordered by `version_number` (1, 2, 3...) and `imported_at`, guarded by `UNIQUE (source_record_id, version_number)`.
  2. Upstream source systems frequently report overlapping, messy, or retroactively corrected attribute validity periods. If PostgreSQL `EXCLUDE` or SQLite triggers rejected overlapping `effective_from/effective_to`, any source extraction with retroactive corrections would trigger a hard RDBMS-level transaction abort, causing catastrophic intake batch crashes and violating DAT 01 ("Zero Data Loss for raw source payloads") and DAT 02 (reconcile and quarantine rather than crashing).
  3. Chronological validity is strictly guarded by:
     - Intra-row sanity check: `CHECK (effective_to IS NULL OR effective_from IS NULL OR effective_to > effective_from)`.
     - Downstream resolution engine: The canonical resolution pipeline evaluates effective dates and selects golden attributes without risking ingestion abortion.

#### B. Canonical Fields (`canonical_fields`)
- **Evaluation Question**: Is a full historical temporal exclusion constraint required, or is "Single ACTIVE field" sufficient?
- **Decision: Single ACTIVE Field via Partial Unique Index; No Historical Exclusion Constraint**.
- **Business & Architectural Rationale**:
  1. **RFP & SRS Requirement (REV 04, FR-REV-04)**: For any canonical entity and field name, there must be **at most one active golden value** at any point in time. This is strictly guaranteed by the partial unique index:
     ```sql
     CREATE UNIQUE INDEX uq_single_active_canonical_field
     ON canonical_fields (canonical_entity_id, field_name)
     WHERE status = 'ACTIVE' AND valid_to IS NULL;
     ```
  2. **Intra-row Interval Sanity**: Enforced via `CHECK (valid_to IS NULL OR valid_to > valid_from)`.
  3. **Atomic Transition Semantics**: Application transactions atomically update the active field row to `status = 'SUPERSEDED'` with `valid_to = :transition_time` and insert the new row with `status = 'ACTIVE'`, `valid_from = :transition_time`, and `valid_to = NULL`.
  4. **Why Full Historical Exclusion is Omitted**: In CRM Master Data Management, data governance teams frequently need to perform retroactive timeline corrections or backfill historical audit evidence (`canonical_field_provenance`) from newly discovered source archives. Adding an engine-level exclusion constraint across historical `SUPERSEDED` rows would lock historical lineage and prevent retroactive administrative reconciliation without any operational benefit to active CRM lookups.

---

## 5. High-Value Indexes & Partial Unique Indexes

### 5.1. Partial Unique Index: Single Active Canonical Field
- **Rule (REV 04)**: For any canonical entity and field name, there must be at most one `ACTIVE` golden value.
  ```sql
  CREATE UNIQUE INDEX uq_single_active_canonical_field
  ON canonical_fields (canonical_entity_id, field_name)
  WHERE status = 'ACTIVE' AND valid_to IS NULL;
  ```
- **Interval Control**: When a new canonical field value is approved, an atomic transaction sets the existing active row's `valid_to = NOW()` and `status = 'SUPERSEDED'`, while inserting the new record with `valid_from = NOW()` and `valid_to = NULL`.

### 5.2. Partial Unique Index: Single Active Cluster Participation
- **Rule (MAT 06)**: A source record cannot participate simultaneously in multiple active candidate clusters.
  ```sql
  CREATE UNIQUE INDEX uq_single_active_cluster_member
  ON candidate_cluster_members (source_record_id)
  WHERE status = 'ACTIVE' AND left_at IS NULL;
  ```

### 5.3. Partial Unique Index: Single Active Distinct Constraint
- **Rule (MAT 05, REV 02)**: Prevent concurrent contradictory distinctness constraints between two entities.
  ```sql
  CREATE UNIQUE INDEX uq_active_distinct_constraint
  ON pair_decision_constraints (left_source_record_id, right_source_record_id)
  WHERE is_active = TRUE AND valid_to IS NULL;
  ```
