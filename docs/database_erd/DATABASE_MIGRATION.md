# DATABASE MIGRATION STRATEGY & TRANSITION PLAN
## SongNhat CRM Duplicate Detection and Entity Resolution System
### Version: 8.5 – Final Targeted Patch (Legacy Entity-Type Compatibility, Full Endpoint Pool Validation & SQLite Transaction Verification)

---

## 1. Migration Architecture & Tooling

To ensure reproducible, auditable database evolutions without manual DDL executions, the project establishes:
- **Migration Framework**: Alembic 1.13+ integrated with SQLAlchemy 2.0.
- **Migration Directory**: `backend/alembic/` (with environment script `env.py` and template `script.py.mako`).
- **Version Tracking**: Standard `alembic_version` table in target database.
- **Environment Parity**: Dual-target migrations supporting both **PostgreSQL 15+** (production/staging) and **SQLite 3.x** (local developer testing with `batch_alter_table`).

---

## 2. Transition Plan from Existing Legacy 3-Table Schema

### 2.1. Prevention of Table Name Collisions
The current legacy database contains three tables:
1. `source_records` (Integer autoincrement PK, non-versioned, flat fields).
2. `candidate_pairs` (Integer autoincrement PK, unlinked string keys).
3. `audit_logs` (Unstructured text logs).

Attempting to run target Alembic DDL directly will trigger a **naming collision failure** (`relation "source_records" already exists`) or cause destructive schema overwrites.

### 2.2. Seven-Step Audited Transition Workflow

```
[Step 1: Pre-Migration Physical Snapshot]
      │ (Timestamped binary backup taken prior to any DDL execution)
      ▼
[Step 2: Staging & Rename Legacy Tables (0001)]
      │ (source_records -> legacy_source_records)
      │ (candidate_pairs -> legacy_candidate_pairs)
      │ (audit_logs -> legacy_audit_logs)
      ▼
[Step 3: Clean Schema Provisioning (0002 to 0007)]
      │ (Deploy full 33-table target architecture with UUIDs)
      ▼
[Step 4: Data Transformation & Provenance Preservation (0008)]
      │ (legacy_source_records -> source_records + source_record_versions v1)
      │ (legacy_candidate_pairs -> candidate_pairs with legacy_reasons_raw; evidence fields NULL)
      │ (legacy_audit_logs -> audit_events marked is_migrated_legacy)
      ▼
[Step 5: Automated Row-by-Row Reconciliation Audit]
      │ (Assert 100% row match; isolate unmapped rows to Quarantine)
      ▼
[Step 6: Seed Default Governance Data (0009)]
      │ (Seed 3 roles, permissions, baseline VN normalization policy v1)
      ▼
[Step 7: Permanent Staging Freeze in Phase 2 (NO AUTOMATIC DROP)]
      │ (Retain legacy_* tables intact indefinitely; DROP requires separate sign-off)
```

#### Step 1: Pre-Migration Backup
Before running any migration script:
- **SQLite**:
  ```bash
  cp data/songnhat_crm.db data/backups/songnhat_crm_pre_migration_$(date +%Y%m%d_%H%M%S).db
  ```
- **PostgreSQL**:
  ```bash
  pg_dump -Fc -h localhost -U songnhat -d songnhat_crm > backups/pre_migration_$(date +%Y%m%d_%H%M%S).dump
  ```

#### Step 2: Staging / Table Renaming
In revision `0001_legacy_staging_rename.py`:
```python
def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()
    
    if "source_records" in existing_tables:
        op.rename_table("source_records", "legacy_source_records")
    if "candidate_pairs" in existing_tables:
        op.rename_table("candidate_pairs", "legacy_candidate_pairs")
    if "audit_logs" in existing_tables:
        op.rename_table("audit_logs", "legacy_audit_logs")
```

#### Step 3: Clean Schema Provisioning
Execute Alembic revisions `0002` through `0007` to create all 33 tables with primary key UUIDs, composite foreign keys, and constraints.

#### Step 4: Data Transformation & Strict Evidence Provenance
In data migration script `0008_migrate_legacy_data.py`:
1. **Register Differentiated Upstream Source Systems**:
   - `CRM_A`: `source_code = 'CRM_A'`, `source_name = 'Legacy CRM System A (Enterprise Accounts)'`, `entity_type = 'ACCOUNT'`.
   - `CRM_B`: `source_code = 'CRM_B'`, `source_name = 'Legacy CRM System B (Regional Branches)'`, `entity_type = 'ACCOUNT'`.
   - `CRM_C`: `source_code = 'CRM_C'`, `source_name = 'Legacy CRM System C (Contact Directory)'`, `entity_type = 'CONTACT'`.
   - All source systems enforce `UNIQUE (id, entity_type)` and all timestamps adhere strictly to `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

2. **Source-Specific Import Batches & Lineage Correlation Manifest**:
   - The target schema enforces composite foreign key `(source_system_id, entity_type)` and batch-source parity. Historical records cannot be collapsed into an ambiguous single batch without violating pool integrity or losing source identity.
   - Therefore, migration revision `0008` provisions **source-specific import batches** for authentic source systems, and a dedicated **unmapped quarantine batch** for records lacking a verifiable source system:
     - `BATCH_CRM_A`: `source_system_id = CRM_A.id`, `batch_type = 'LEGACY_MIGRATION'`, `file_name = 'legacy_source_records/CRM_A'`, `file_checksum = SHA256('LEGACY_MIGRATION_0008_CRM_A')`, `batch_status = 'COMPLETED'`.
     - `BATCH_CRM_B`: `source_system_id = CRM_B.id`, `batch_type = 'LEGACY_MIGRATION'`, `file_name = 'legacy_source_records/CRM_B'`, `file_checksum = SHA256('LEGACY_MIGRATION_0008_CRM_B')`, `batch_status = 'COMPLETED'`.
     - `BATCH_CRM_C`: `source_system_id = CRM_C.id`, `batch_type = 'LEGACY_MIGRATION'`, `file_name = 'legacy_source_records/CRM_C'`, `file_checksum = SHA256('LEGACY_MIGRATION_0008_CRM_C')`, `batch_status = 'COMPLETED'`.
     - `BATCH_UNMAPPED_QUARANTINE`: `source_system_id = NULL`, `batch_type = 'UNMAPPED_QUARANTINE'`, `file_name = 'legacy_source_records/unmapped'`, `file_checksum = SHA256('LEGACY_MIGRATION_0008_UNMAPPED')`, `batch_status = 'QUARANTINED'`.
       - *Zero Fabrication Guarantee*: Records lacking a verifiable `source_system` are quarantined with `source_system_id = NULL` satisfying `CHECK (batch_type = 'UNMAPPED_QUARANTINE' OR source_system_id IS NOT NULL)`. **No fake source system (e.g. CRM_UNKNOWN) is created, and no record is falsely attributed to CRM_A/B/C**.
   - **True Nature of Candidate Pairs & Matching Run Correlation**:
     - Candidate pairs represent comparison edges between two source records across systems; they **do not belong to a single source system and are NOT source intake records**. Assuming CRM_A (or any single source) is the source of all candidate pairs is fundamentally invalid.
     - Therefore, legacy candidate pairs are **NOT placed into `import_batches`**. Instead, they are governed by their authentic parent entity: **`matching_runs`**.
     - Because the target schema enforces strict entity pool segregation (`entity_pool` is NOT NULL: `'ACCOUNT'` or `'CONTACT'`), migration revision `0008` provisions **two dedicated matching runs** in `matching_runs` **using only existing schema fields** (without inventing extraneous fields):
       ```sql
       -- ====================================================================
       -- TRANSACTION STEP 4.1: INITIALIZE MATCHING RUNS IN 'RUNNING' STATE
       -- ====================================================================
       -- To guarantee transactional ordering and schema consistency:
       -- 1. Matching runs are initialized with status = 'RUNNING' and total_candidates = 0.
       -- 2. Candidate pairs are inserted.
       -- 3. total_candidates is updated to actual count and status updated to 'COMPLETED'.

       -- 1. Matching Run for Migrated Account Pairs (RUNNING state)
       INSERT INTO matching_runs (
           id, run_code, entity_pool, status, policy_id, 
           total_candidates, ceiling_breached, started_at, completed_at, 
           executed_by, notes, created_at
       ) VALUES (
           :legacy_matching_run_account_id,
           'MIG-0008-HISTORICAL-PAIRS-ACCOUNT',
           'ACCOUNT',
           'RUNNING',
           :baseline_policy_id,
           0,
           FALSE,
           NOW(),
           NULL,
           :migration_admin_id,
           'Legacy migration revision 0008: historical candidate pairs consolidation manifest (ACCOUNT pool)',
           NOW()
       );

       -- 2. Matching Run for Migrated Contact Pairs (RUNNING state)
       INSERT INTO matching_runs (
           id, run_code, entity_pool, status, policy_id, 
           total_candidates, ceiling_breached, started_at, completed_at, 
           executed_by, notes, created_at
       ) VALUES (
           :legacy_matching_run_contact_id,
           'MIG-0008-HISTORICAL-PAIRS-CONTACT',
           'CONTACT',
           'RUNNING',
           :baseline_policy_id,
           0,
           FALSE,
           NOW(),
           NULL,
           :migration_admin_id,
           'Legacy migration revision 0008: historical candidate pairs consolidation manifest (CONTACT pool)',
           NOW()
       );
       ```
     - **Cross-Batch Lineage Correlation via `run_sources`**:
       - Table `run_sources` links `:legacy_matching_run_account_id` to its intake batches (`BATCH_CRM_A`, `BATCH_CRM_B`) and `:legacy_matching_run_contact_id` to `BATCH_CRM_C`.
       - Quarantined batch `BATCH_UNMAPPED_QUARANTINE` has `source_system_id = NULL` and is **never linked to `run_sources`**, strictly respecting `run_sources.source_system_id NOT NULL`.
       - With `CONSTRAINT uq_run_source_batch UNIQUE (matching_run_id, import_batch_id)` and Composite FK `FOREIGN KEY (import_batch_id, source_system_id) REFERENCES import_batches (id, source_system_id)`, each matching run can safely incorporate **multiple batches from the same source system** while the database engine strictly guarantees that every linked batch authenticates with its declared source system.

3. **Deterministic Legacy Record Classification & Source Integrity Rules**:
   Every row in `legacy_source_records` is evaluated through the intake engine and mapped to **exactly one final outcome**: `MIGRATED`, `QUARANTINED`, or `REJECTED`.
   
   - **Pre-Validation: Source Key and Source System Validity**:
     - *Missing or Unrecognized Source System*: If `legacy.source_system` is NULL, empty, or not in (`CRM_A`, `CRM_B`, `CRM_C`), mark `QUARANTINED` in `batch_row_results` with reason `INVALID_SOURCE_SYSTEM: Value missing or unmapped in source system registry`.
     - *Missing Source Key*: If `legacy.source_key` is NULL or whitespace, mark `REJECTED` in `batch_row_results` with reason `MISSING_SOURCE_KEY: Persistent identity anchor cannot be established`.
     - *Duplicate Source Key within Same System*: If multiple legacy rows share identical `(source_system, source_key)`:
       - **Strict Rule: DO NOT arbitrarily pick the first row or fabricate mappings**.
       - **ALL duplicate rows** are marked `QUARANTINED` in `batch_row_results` with reason `DUPLICATE_SOURCE_KEY_IN_SOURCE: Key appears multiple times in legacy intake`. They are withheld from `source_records` to prevent unique index violation and await Data Steward de-duplication.

   - **Entity Type & Subtype Derivation**:
     - **Rule A (CRM_A / CRM_B - ACCOUNT Pool)**:
       - If `legacy.entity_type IN ('COMPANY', 'ENTERPRISE', 'ORGANIZATION')` -> `entity_type = 'ACCOUNT'`, `entity_subtype = 'COMPANY'`.
       - If `legacy.entity_type IN ('BRANCH', 'OFFICE', 'FACTORY')` -> `entity_type = 'ACCOUNT'`, `entity_subtype = 'BRANCH'`.
       - If `legacy.entity_type IN ('SITE', 'STORE', 'WAREHOUSE')` -> `entity_type = 'ACCOUNT'`, `entity_subtype = 'SITE'`.
       - If `legacy.entity_type` is NULL/unspecified but verifiable `tax_code` is present -> `entity_type = 'ACCOUNT'`, `entity_subtype = 'COMPANY'`.
     - **Rule B (CRM_C - CONTACT Pool)**:
       - If `legacy.entity_type IN ('CONTACT', 'PERSON', 'INDIVIDUAL', 'LEAD')` -> `entity_type = 'CONTACT'`, `entity_subtype = 'PERSON'`.
     - **Rule C (Strict Quarantine on Ambiguity or Pool Mismatch - Zero Speculation)**:
       - If `legacy.entity_type` contradicts the registered source system pool (e.g. record in `CRM_A` claiming `CONTACT`, or record in `CRM_C` containing corporate `tax_code` / claiming `COMPANY`), OR
       - If `legacy.entity_type` is NULL/unrecognized and lacks unequivocal attribute proof:
         - **DO NOT GUESS OR FABRICATE AN ENTITY TYPE**.
         - Route row directly to `batch_row_results` with `row_status = 'QUARANTINED'` and `validation_errors = 'UNRESOLVED_ENTITY_TYPE_AMBIGUITY: Source system expects pool parity but record contains contradictory or insufficient evidence.'`.
         - Row remains safely archived in `legacy_source_records` and `batch_row_results`.
         - It is **NOT** inserted into `source_records`, completely preventing breach of composite foreign key `(source_system_id, entity_type)`.

   - **Execution for MIGRATED Rows**:
     - Generate a new `UUIDv4` identifier.
     - Insert into `source_records (id, source_system_id, source_key, entity_type, entity_subtype, created_at)` satisfying composite FK `(source_system_id, entity_type) REFERENCES source_systems (id, entity_type)`.
     - Insert into `source_record_versions (id, source_record_id, version_number=1, raw_payload=JSON(...), checksum=SHA256(...), imported_at)`.
     - If `tax_code` is present, insert into `source_identifiers (identifier_type='TAX_ID_10' or 'TAX_ID_13', identifier_value=tax_code)`.
     - Record in `batch_row_results`: `row_status = 'ACCEPTED'`, `source_record_id = id`, `source_record_version_id = version_id`.

4. **Deterministic Legacy Candidate Pairs Mapping, Endpoint Resolution & 5-Stage Precedence Hierarchy**:
   - **Architectural Scope Alignment**: Candidate pairs represent multi-source comparison edges generated by the matching engine. They **belong directly to `matching_runs`**, not to single-source `import_batches`. Assuming CRM_A is the source system of all candidate pairs is fundamentally invalid.
   - **Legacy Schema Context & Cross-CRM Key Collision Reality**:
     - In the legacy database, `legacy_candidate_pairs` stores only `left_source_key` and `right_source_key`; it does **NOT** record the source systems of the two endpoints.
     - In `legacy_source_records`, uniqueness was only guaranteed within each individual CRM (`UNIQUE (source_system, source_key)`). Therefore, identical `source_key` values may collide across CRMs (e.g., `ACC-001` in CRM_A and `ACC-001` in CRM_B).
     - **Zero Speculation Rule**: If a `source_key` appears more than once across all legacy records, its CRM origin cannot be determined authentically. The system **MUST NOT arbitrarily pick a record** or guess the CRM. Such pairs are routed to `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT`.
   - **Strict Mutually Exclusive 5-Stage Precedence Hierarchy**:
     Every legacy pair in `legacy_candidate_pairs` is evaluated through a strict cascade of mutually exclusive rules, ensuring no pair belongs to multiple groups and that `PAIR_MIGRATED` is never assigned purely because a physical row exists:
     1. **Precedence 1: Dangling Key (`PAIR_REJECTED_DANGLING_KEY`)**:
        - Condition: `left_source_key` OR `right_source_key` does not exist anywhere in `legacy_source_records` ($L_{cnt} = 0 \lor R_{cnt} = 0$).
        - Action: Reject missing reference. Do NOT insert into `candidate_pairs`.
     2. **Precedence 2: Ambiguous Endpoint (`PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT`)**:
        - Condition: `left_source_key` OR `right_source_key` appears > 1 time across `legacy_source_records` ($L_{cnt} > 1 \lor R_{cnt} > 1$).
        - Action: Multi-CRM collision or duplicate key in source. Do NOT speculate or link to first record. Quarantine and preserve in `legacy_candidate_pairs`.
     3. **Precedence 3: Quarantined Endpoint (`PAIR_QUARANTINED_ENDPOINT`)**:
        - Condition: Both keys exist uniquely in legacy ($L_{cnt} = 1 \land R_{cnt} = 1$), but at least one endpoint was held in source intake Quarantine (i.e. did not create a target `source_records` entry).
        - Action: Cannot link to non-existent target record. Quarantine pair and preserve in `legacy_candidate_pairs`.
     4. **Precedence 4: Cross-Pool Mismatch (`PAIR_REJECTED_CROSS_POOL_MISMATCH`)**:
        - Condition: Both endpoints uniquely migrated, but one is an `ACCOUNT` and the other is a `CONTACT` ($L_{rec}.entity\_type \ne R_{rec}.entity\_type$).
        - Action: Cross-pool matching is prohibited by CRM domain boundaries and composite FKs. Reject and preserve in `legacy_candidate_pairs`.
     5. **Precedence 5: Migrated Valid Pair (`PAIR_MIGRATED`)**:
        - Condition: Both endpoints uniquely identified, both successfully migrated, both share identical entity pool (`ACCOUNT` or `CONTACT`), and physical candidate pair exists with:
          * `legacy_pair_id = legacy.id` (1:1 anchor)
          * `matching_run_id` matches expected pool run (`MIG-0008-HISTORICAL-PAIRS-ACCOUNT` or `MIG-0008-HISTORICAL-PAIRS-CONTACT`)
          * `left_source_record_id = min(L.id, R.id)` and `right_source_record_id = max(L.id, R.id)`
          * `entity_type = L.entity_type`
          * `is_migrated_legacy = TRUE`
        - Action: Insert into `candidate_pairs` and insert unclassified legacy evidence into `candidate_pair_evidence`:
          * `field_name = 'legacy_reasons'`, `explanation = legacy.reasons`
          * `similarity_score = NULL`, `evidence_direction = NULL`, `evidence_weight = NULL`, `policy_version = NULL`
          * `is_legacy_evidence = TRUE`, `provenance = 'LEGACY_MIGRATION'`.

   *Governance Guarantee*: All pairs that cannot be migrated are preserved verbatim in `legacy_candidate_pairs`. Zero fake pairs are created, zero pairs are silently dropped, and zero fake source attribution is used.

5. **Legacy Audit Logs Lineage**:
   For each row in `legacy_audit_logs`:
   - Preserve original `action`, `actor`, `role`, `target_pair`, `reason`, and `created_at`.
   - Map into `audit_events`: `is_migrated_legacy = TRUE`, `hash_generated_at_migration = TRUE`.
   - Calculate SHA-256 hash from legacy fields at migration instant.
   - *Important Governance Note*: This hash represents record state at migration time and **does not assert retrospective immutability** of pre-migration history.

6. **Post-Insertion Matching Run Finalization (Transaction Step 4.2)**:
   After all migrated candidate pairs have been inserted into `candidate_pairs`, the migration transaction updates `matching_runs` with the authentic candidate counts and sets status to `COMPLETED`:
   ```sql
   -- Update Account Matching Run metrics
   UPDATE matching_runs 
   SET total_candidates = (
       SELECT COUNT(*) 
       FROM candidate_pairs 
       WHERE matching_run_id = :legacy_matching_run_account_id
   ),
   status = 'COMPLETED',
   completed_at = NOW()
   WHERE id = :legacy_matching_run_account_id;

   -- Update Contact Matching Run metrics
   UPDATE matching_runs 
   SET total_candidates = (
       SELECT COUNT(*) 
       FROM candidate_pairs 
       WHERE matching_run_id = :legacy_matching_run_contact_id
   ),
   status = 'COMPLETED',
   completed_at = NOW()
   WHERE id = :legacy_matching_run_contact_id;
   ```

#### Step 5: Audited Row-Level Reconciliation (Conservation of Records)

Reconciliation operates on the strict mathematical law of **Conservation of Records**: every legacy row and candidate pair must be accounted for in **exactly one category**, eliminating any possibility of double counting or silent data loss.

```sql
-- ============================================================================
-- 1. SOURCE RECORDS CONSERVATION & RECONCILIATION (ALL SOURCE & QUARANTINE BATCHES)
-- ============================================================================
WITH legacy_source_summary AS (
    SELECT 
        COUNT(*) AS total_legacy_rows,
        COUNT(CASE WHEN source_system = 'CRM_A' THEN 1 END) AS legacy_crm_a_rows,
        COUNT(CASE WHEN source_system = 'CRM_B' THEN 1 END) AS legacy_crm_b_rows,
        COUNT(CASE WHEN source_system = 'CRM_C' THEN 1 END) AS legacy_crm_c_rows,
        COUNT(CASE WHEN source_system NOT IN ('CRM_A', 'CRM_B', 'CRM_C') OR source_system IS NULL THEN 1 END) AS legacy_unmapped_system_rows
    FROM legacy_source_records
),
intake_outcomes AS (
    SELECT 
        COUNT(CASE WHEN brr.row_status = 'ACCEPTED' THEN 1 END) AS migrated_count,
        COUNT(CASE WHEN brr.row_status = 'QUARANTINED' THEN 1 END) AS quarantined_count,
        COUNT(CASE WHEN brr.row_status = 'REJECTED' THEN 1 END) AS rejected_count,
        COUNT(*) AS total_evaluated_rows
    FROM batch_row_results brr
    JOIN import_batches ib ON brr.import_batch_id = ib.id
    WHERE ib.batch_type IN ('LEGACY_MIGRATION', 'UNMAPPED_QUARANTINE')
),
physical_source_verification AS (
    SELECT 
        (SELECT COUNT(*) 
         FROM source_record_versions srv 
         JOIN import_batches ib ON srv.import_batch_id = ib.id 
         WHERE ib.batch_type = 'LEGACY_MIGRATION' AND srv.version_number = 1) AS physical_v1_count,
        (SELECT COUNT(DISTINCT srv.source_record_id) 
         FROM source_record_versions srv 
         JOIN import_batches ib ON srv.import_batch_id = ib.id 
         WHERE ib.batch_type = 'LEGACY_MIGRATION' AND srv.version_number = 1) AS distinct_migrated_records
)
SELECT 
    l.total_legacy_rows,
    i.total_evaluated_rows,
    i.migrated_count,
    i.quarantined_count,
    i.rejected_count,
    p.physical_v1_count,
    p.distinct_migrated_records,
    -- Assertion 1: Conservation of Source Rows (Total Legacy == Evaluated == Migrated + Quarantined + Rejected)
    CASE WHEN l.total_legacy_rows = i.total_evaluated_rows 
              AND l.total_legacy_rows = (i.migrated_count + i.quarantined_count + i.rejected_count) 
         THEN 'PASS' ELSE 'FAIL_ROW_CONSERVATION' END AS row_conservation_status,
    -- Assertion 2: Physical Parity (Every MIGRATED row has exactly 1 version 1 and 1 distinct source_record)
    CASE WHEN i.migrated_count = p.physical_v1_count 
              AND i.migrated_count = p.distinct_migrated_records 
         THEN 'PASS' ELSE 'FAIL_PHYSICAL_PARITY' END AS physical_integrity_status,
    -- Assertion 3: Quarantine Isolation (Zero quarantined rows leaked into source_records)
    CASE WHEN (SELECT COUNT(*) 
               FROM batch_row_results brr 
               JOIN import_batches ib ON brr.import_batch_id = ib.id 
               WHERE ib.batch_type IN ('LEGACY_MIGRATION', 'UNMAPPED_QUARANTINE') 
                 AND brr.row_status = 'QUARANTINED' 
                 AND brr.source_record_id IS NOT NULL) = 0 
         THEN 'PASS' ELSE 'FAIL_QUARANTINE_LEAK' END AS quarantine_isolation_status
FROM legacy_source_summary l, intake_outcomes i, physical_source_verification p;


-- ============================================================================
-- 2. CANDIDATE PAIRS TWO-WAY PHYSICAL PARITY & CONSERVATION RECONCILIATION
-- ============================================================================
WITH 
legacy_pair_summary AS (
    SELECT COUNT(*) AS total_legacy_pairs FROM legacy_candidate_pairs
),

-- Pre-aggregate legacy source multiplicity to detect cross-CRM collisions without row multiplying
left_counts AS (
    SELECT source_key, COUNT(*) AS cnt
    FROM legacy_source_records
    GROUP BY source_key
),
right_counts AS (
    SELECT source_key, COUNT(*) AS cnt
    FROM legacy_source_records
    GROUP BY source_key
),

-- Step 1: Identify source keys that exist EXACTLY ONCE across all legacy source records
-- Disallows inconsistent entity types for the same source key; strictly maps legacy entity types to CRM pools:
-- COMPANY -> ACCOUNT, BRANCH -> ACCOUNT, CONTACT -> CONTACT.
-- Rejects/quarantines unknown legacy entity types and does NOT mask inconsistencies with MIN().
unique_legacy_keys AS (
    SELECT 
        source_key,
        MIN(source_system) AS source_system,
        MIN(entity_type) AS raw_legacy_entity_type,
        CASE 
            WHEN MIN(entity_type) IN ('COMPANY', 'BRANCH') THEN 'ACCOUNT'
            WHEN MIN(entity_type) = 'CONTACT' THEN 'CONTACT'
            ELSE 'UNKNOWN'
        END AS mapped_entity_pool
    FROM legacy_source_records
    GROUP BY source_key
    HAVING COUNT(*) = 1 
       AND COUNT(DISTINCT CASE 
               WHEN entity_type IN ('COMPANY', 'BRANCH') THEN 'ACCOUNT'
               WHEN entity_type = 'CONTACT' THEN 'CONTACT'
               ELSE 'UNKNOWN' 
           END) = 1
       AND MIN(entity_type) IN ('COMPANY', 'BRANCH', 'CONTACT')
),

-- Step 2: Uniquely migrated endpoints in target source_records with strict source-system and entity-type parity
-- Strict bidirectional compatibility:
-- 1. Legacy COMPANY / BRANCH only join ACCOUNT source_systems and ACCOUNT source_records.
-- 2. Legacy CONTACT only joins CONTACT source_systems and CONTACT source_records.
-- 3. Does not use MIN(entity_type) to mask inconsistencies.
-- 4. Immune to row duplication because import_batches is not joined.
-- 5. Subtype mapping assumption: COMPANY and BRANCH are unified into the ACCOUNT pool; subtype distinction
--    is preserved in record_payload and normalized attributes (requires formal Data Owner sign-off).
unique_migrated_sources AS (
    SELECT 
        ulk.source_key,
        ulk.source_system AS legacy_source_system,
        ulk.raw_legacy_entity_type,
        ulk.mapped_entity_pool,
        sr.id AS source_record_id,
        sr.entity_type,
        ss.source_code AS target_source_code
    FROM unique_legacy_keys ulk
    JOIN source_systems ss 
        ON ss.source_code = ulk.source_system
       AND ss.entity_type = ulk.mapped_entity_pool
    JOIN source_records sr 
        ON sr.source_key = ulk.source_key 
       AND sr.source_system_id = ss.id 
       AND sr.entity_type = ulk.mapped_entity_pool
),

-- Strict 5-Stage Mutually Exclusive Classification Cascade
legacy_pair_outcomes AS (
    SELECT 
        lcp.id AS legacy_pair_id,
        lcp.left_source_key,
        lcp.right_source_key,
        l_mig.source_record_id AS expected_left_id,
        r_mig.source_record_id AS expected_right_id,
        l_mig.entity_type AS expected_entity_type,
        CASE 
            -- Precedence 1: Dangling Key (Key does not exist anywhere in legacy sources)
            WHEN COALESCE(lc.cnt, 0) = 0 OR COALESCE(rc.cnt, 0) = 0 
                THEN 'PAIR_REJECTED_DANGLING_KEY'
                
            -- Precedence 2: Ambiguous Endpoint (Key matches > 1 legacy records across or within CRMs)
            WHEN lc.cnt > 1 OR rc.cnt > 1 
                THEN 'PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT'
                
            -- Precedence 3: Quarantined Endpoint (Endpoint existed uniquely in legacy, but was quarantined during intake)
            WHEN l_mig.source_record_id IS NULL OR r_mig.source_record_id IS NULL 
                THEN 'PAIR_QUARANTINED_ENDPOINT'
                
            -- Precedence 4: Cross-Pool Mismatch (Left and right endpoints belong to different entity pools)
            WHEN l_mig.entity_type <> r_mig.entity_type 
                THEN 'PAIR_REJECTED_CROSS_POOL_MISMATCH'
                
            -- Precedence 5: Migrated (Both endpoints unique, migrated, same pool, and candidate_pair verified)
            WHEN cp.id IS NOT NULL 
                AND cp.legacy_pair_id = lcp.id
                AND cp.matching_run_id = (CASE WHEN l_mig.entity_type = 'ACCOUNT' THEN :legacy_matching_run_account_id ELSE :legacy_matching_run_contact_id END)
                AND cp.left_source_record_id = LEAST(l_mig.source_record_id, r_mig.source_record_id)
                AND cp.right_source_record_id = GREATEST(l_mig.source_record_id, r_mig.source_record_id)
                AND cp.entity_type = l_mig.entity_type
                AND cp.is_migrated_legacy = TRUE
                THEN 'PAIR_MIGRATED'
                
            -- Internal Discrepancy indicator (Signals unmapped pair; causes immediate transaction rollback)
            ELSE 'PAIR_UNMAPPED_DISCREPANCY'
        END AS terminal_status
    FROM legacy_candidate_pairs lcp
    LEFT JOIN left_counts lc ON lc.source_key = lcp.left_source_key
    LEFT JOIN right_counts rc ON rc.source_key = lcp.right_source_key
    LEFT JOIN unique_migrated_sources l_mig ON l_mig.source_key = lcp.left_source_key AND lc.cnt = 1
    LEFT JOIN unique_migrated_sources r_mig ON r_mig.source_key = lcp.right_source_key AND rc.cnt = 1
    LEFT JOIN candidate_pairs cp 
        ON cp.legacy_pair_id = lcp.id 
       AND cp.matching_run_id IN (:legacy_matching_run_account_id, :legacy_matching_run_contact_id) 
       AND cp.is_migrated_legacy = TRUE
),

categorized_outcomes AS (
    SELECT 
        COUNT(CASE WHEN terminal_status = 'PAIR_MIGRATED' THEN 1 END) AS pair_migrated_count,
        COUNT(CASE WHEN terminal_status = 'PAIR_QUARANTINED_ENDPOINT' THEN 1 END) AS pair_quarantined_endpoint_count,
        COUNT(CASE WHEN terminal_status = 'PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT' THEN 1 END) AS pair_quarantined_ambiguous_count,
        COUNT(CASE WHEN terminal_status = 'PAIR_REJECTED_DANGLING_KEY' THEN 1 END) AS pair_rejected_dangling_count,
        COUNT(CASE WHEN terminal_status = 'PAIR_REJECTED_CROSS_POOL_MISMATCH' THEN 1 END) AS pair_rejected_cross_pool_count,
        COUNT(CASE WHEN terminal_status = 'PAIR_UNMAPPED_DISCREPANCY' THEN 1 END) AS pair_unmapped_discrepancy_count,
        COUNT(*) AS total_evaluated_pairs
    FROM legacy_pair_outcomes
),

-- Physical-to-Legacy Scope (Checking all physical candidate_pairs created by migration 0008)
physical_scope AS (
    SELECT 
        cp.id,
        cp.legacy_pair_id,
        cp.matching_run_id,
        cp.entity_type,
        cp.left_source_record_id,
        cp.right_source_record_id,
        lcp.id AS matched_legacy_id,
        lcp.left_source_key,
        lcp.right_source_key
    FROM candidate_pairs cp
    LEFT JOIN legacy_candidate_pairs lcp ON cp.legacy_pair_id = lcp.id
    WHERE cp.matching_run_id IN (:legacy_matching_run_account_id, :legacy_matching_run_contact_id)
      AND cp.is_migrated_legacy = TRUE
),

-- Physical Endpoint Parity Check: 100% NULL-SAFE verification that physical pairs match authentic target endpoints
-- Explicitly prevents three-valued logic (3VL) NULL comparison traps from falling into ELSE 0.
-- Bilaterally asserts endpoint pool consistency and canonical ID ordering.
physical_endpoint_verification AS (
    SELECT 
        ps.id,
        CASE WHEN ps.matched_legacy_id IS NULL THEN 1 ELSE 0 END AS is_orphan,
        CASE WHEN ps.legacy_pair_id IS NULL THEN 1 ELSE 0 END AS is_missing_legacy_id,
        CASE 
            -- 1. NULL safety: Any endpoint ID or entity_type is NULL in physical pair or expected target
            WHEN l_mig.source_record_id IS NULL 
              OR r_mig.source_record_id IS NULL
              OR ps.left_source_record_id IS NULL 
              OR ps.right_source_record_id IS NULL
              OR ps.entity_type IS NULL
              OR l_mig.entity_type IS NULL
              OR r_mig.entity_type IS NULL
                THEN 1
            -- 2. Pool consistency: Left and right target pools differ, or physical pair pool differs from either endpoint
            WHEN l_mig.entity_type <> r_mig.entity_type 
              OR ps.entity_type <> l_mig.entity_type 
              OR ps.entity_type <> r_mig.entity_type 
                THEN 1
            -- 3. Left endpoint mismatch (must strictly match LEAST under canonical ordering)
            WHEN ps.left_source_record_id <> LEAST(l_mig.source_record_id, r_mig.source_record_id) 
                THEN 1
            -- 4. Right endpoint mismatch (must strictly match GREATEST under canonical ordering)
            WHEN ps.right_source_record_id <> GREATEST(l_mig.source_record_id, r_mig.source_record_id) 
                THEN 1
            -- Valid only when all values are strictly NOT NULL, pools mutually consistent, and canonical order verified
            ELSE 0 
        END AS is_endpoint_mismatch
    FROM physical_scope ps
    LEFT JOIN unique_migrated_sources l_mig ON l_mig.source_key = ps.left_source_key
    LEFT JOIN unique_migrated_sources r_mig ON r_mig.source_key = ps.right_source_key
),
physical_metrics AS (
    SELECT 
        COUNT(*) AS physical_migrated_count,
        COUNT(legacy_pair_id) AS physical_with_legacy_id_count,
        COUNT(DISTINCT legacy_pair_id) AS physical_distinct_legacy_id_count,
        (SELECT SUM(is_orphan) FROM physical_endpoint_verification) AS physical_orphan_count,
        (SELECT SUM(is_endpoint_mismatch) FROM physical_endpoint_verification) AS physical_endpoint_mismatch_count,
        COUNT(CASE WHEN matching_run_id = :legacy_matching_run_account_id AND entity_type <> 'ACCOUNT' THEN 1 
                   WHEN matching_run_id = :legacy_matching_run_contact_id AND entity_type <> 'CONTACT' THEN 1 END) AS physical_pool_mismatch_count
    FROM physical_scope
),

-- Matching Runs Metric Verification
run_metrics AS (
    SELECT 
        SUM(total_candidates) AS runs_total_candidates,
        COUNT(CASE WHEN status <> 'COMPLETED' THEN 1 END) AS incomplete_runs_count
    FROM matching_runs
    WHERE id IN (:legacy_matching_run_account_id, :legacy_matching_run_contact_id)
)

SELECT 
    lp.total_legacy_pairs,
    co.total_evaluated_pairs,
    co.pair_migrated_count,
    co.pair_quarantined_endpoint_count,
    co.pair_quarantined_ambiguous_count,
    co.pair_rejected_dangling_count,
    co.pair_rejected_cross_pool_count,
    co.pair_unmapped_discrepancy_count,
    pm.physical_migrated_count,
    pm.physical_orphan_count,
    pm.physical_endpoint_mismatch_count,
    pm.physical_pool_mismatch_count,
    rm.runs_total_candidates,
    rm.incomplete_runs_count,

    -- Assertion A (Legacy-to-Physical Parity):
    -- Every PAIR_MIGRATED has exactly 1 physical row with matching endpoints, pool, and legacy_pair_id.
    -- If discrepancy count > 0, this assertion FAILS and triggers immediate ROLLBACK.
    CASE WHEN co.pair_unmapped_discrepancy_count = 0 
              AND co.pair_migrated_count = pm.physical_migrated_count 
         THEN 'PASS' ELSE 'FAIL_LEGACY_TO_PHYSICAL' END AS legacy_to_physical_assertion,

    -- Assertion B (Physical-to-Legacy Parity & Endpoint Integrity):
    -- Zero orphan migrated pairs, zero duplicate legacy_pair_ids, zero pool mismatches, zero endpoint mismatches.
    CASE WHEN pm.physical_orphan_count = 0 
              AND pm.physical_migrated_count = pm.physical_distinct_legacy_id_count 
              AND pm.physical_pool_mismatch_count = 0
              AND pm.physical_endpoint_mismatch_count = 0
         THEN 'PASS' ELSE 'FAIL_PHYSICAL_TO_LEGACY' END AS physical_to_legacy_assertion,

    -- Assertion C (Conservation of Candidate Pairs):
    -- Total legacy pairs == Total evaluated == Sum of 5 mutually exclusive terminal outcomes.
    -- (Discrepancy pairs do NOT count as success; if any exist, conservation test FAILS).
    CASE WHEN co.pair_unmapped_discrepancy_count = 0
              AND lp.total_legacy_pairs = co.total_evaluated_pairs
              AND lp.total_legacy_pairs = (
                  co.pair_migrated_count + 
                  co.pair_quarantined_endpoint_count + 
                  co.pair_quarantined_ambiguous_count + 
                  co.pair_rejected_dangling_count + 
                  co.pair_rejected_cross_pool_count
              )
         THEN 'PASS' ELSE 'FAIL_PAIR_CONSERVATION' END AS pair_conservation_assertion,

    -- Assertion D (Run Parity):
    -- matching_runs.total_candidates must exactly equal physical migrated count and status must be COMPLETED.
    CASE WHEN rm.runs_total_candidates = pm.physical_migrated_count 
              AND rm.incomplete_runs_count = 0 
         THEN 'PASS' ELSE 'FAIL_RUN_METRICS_PARITY' END AS run_parity_assertion

FROM legacy_pair_summary lp, categorized_outcomes co, physical_metrics pm, run_metrics rm;
```

#### Step 6: Distinction Between Valid Quarantine and Critical Migration Failure
- **Valid Quarantine (Success)**: When every single legacy row and pair has a documented resolution status, each quarantined row has an explicit provenance reason in `batch_row_results`, and row conservation assertions evaluate to `PASS`, the migration is considered **100% complete and reconciled**. Valid quarantine is NOT data loss; it is proper governance isolating unverified source data.
- **Critical Migration Failure (Rollback Required)**: If any row conservation check fails (`FAIL_ROW_CONSERVATION` or `FAIL_PAIR_CONSERVATION`), if rows exist without status, or if composite foreign key violations occur, migration 0008 raises `RuntimeError` and triggers an immediate transaction abort, requiring restoration of the verified physical snapshot created in Step 1.
- **Strict Prohibition on Deleting Legacy Tables**: Under NO circumstances may `legacy_source_records`, `legacy_candidate_pairs`, or `legacy_audit_logs` be dropped or truncated to force reconciliation numbers to match.

#### Step 7: Permanent Staging Freeze in Phase 2 (NO DROP POLICY)
- **Strict Policy**: Legacy tables (`legacy_source_records`, `legacy_candidate_pairs`, `legacy_audit_logs`) will **NOT** be dropped in Phase 2.
- They remain in read-only state until formal sign-off at Release Gate G1.
- Decommissioning is explicitly deferred to a dedicated post-G1 revision (`0010_decommission_legacy_tables.py`), executed only after formal written authorization.

---


---

## 3.1. Idempotency State Machine & Replay Protection Policy (Migration 0008)

Migration revision `0008_migrate_legacy_data.py` replaces simplistic count checks with a comprehensive **State-Machine Idempotency Guard**:

```
                              [Start Migration 0008]
                                        │
             ┌──────────────────────────┴──────────────────────────┐
             ▼                                                     ▼
     [PostgreSQL Dialect]                                  [SQLite Dialect]
  pg_advisory_xact_lock(hashtext(...))                   BEGIN IMMEDIATE / EXCLUSIVE
             │                                                     │
             └──────────────────────────┬──────────────────────────┘
                                        ▼
                   [Query Existing Matching Runs Status]
                                        │
     ┌──────────────────────┬───────────┴───────────┬──────────────────────┐
     ▼                      ▼                       ▼                      ▼
[State A: None Exist]  [State C: Only 1]    [State B: Both COMPLETED  [State D: Both Exist
  Ready to migrate;     Inconsistent state;  & Reconciled PASS]         but Reconciliation
  execute Step 4.       Fail-Closed; abort.  Idempotent Success;       FAILED]
                                             exit safely (no-op).      Fail-Closed; abort.
```

### Detailed Evaluation of the 5 Idempotency Scenarios:
1. **Scenario A: No matching runs exist (`STATE_READY_TO_MIGRATE`)**:
   - Pre-condition verified. The transaction proceeds to provision matching runs in `RUNNING` state and execute data transformation.
2. **Scenario B: Both matching runs exist and fully reconciled (`STATE_IDEMPOTENT_SUCCESS`)**:
   - Verifies `run_code` (`MIG-0008-HISTORICAL-PAIRS-ACCOUNT` and `MIG-0008-HISTORICAL-PAIRS-CONTACT`), `entity_pool` (`ACCOUNT` and `CONTACT`), and `status = 'COMPLETED'`.
   - Executes the complete Two-Way Physical Parity & Conservation reconciliation query.
   - If all 4 assertions (`legacy_to_physical`, `physical_to_legacy`, `pair_conservation`, `run_parity`) evaluate to `PASS`, migration 0008 recognizes that the transformation was previously completed. It logs an informational audit message and exits safely without creating duplicate runs or pairs.
3. **Scenario C: Only one matching run exists (`STATE_INCONSISTENT_PARTIAL_RUNS`)**:
   - **Fail-Closed Principle**: The system **MUST NOT blindly create the missing run**. Having only one run indicates a prior non-transactional crash or administrative corruption.
   - Action: Raises `RuntimeError("CRITICAL: Inconsistent migration state: only one matching run exists. Automated recovery blocked. Restore from Step 1 physical binary snapshot.")`.
4. **Scenario D: Both matching runs exist but reconciliation FAILS (`STATE_CORRUPTED_EXISTING_RUNS`)**:
   - If runs exist but any parity or conservation assertion fails, or `status <> 'COMPLETED'`:
   - **Strict Governance**: The system **MUST NOT ignore errors, MUST NOT delete candidate pairs, and MUST NOT drop legacy tables**.
   - Action: Raises `RuntimeError("CRITICAL: Existing migration runs failed reconciliation assertions. Lineage integrity compromised. Restore from Step 1 physical backup.")`.
5. **Scenario E: Concurrent migration executions & Alembic Transaction Locking Lifecycle**:
   - **PostgreSQL Implementation**:
     * Before evaluating any migration state, revision `0008` executes:
       ```sql
       SELECT pg_advisory_xact_lock(hashtext('MIG_0008_HISTORICAL_PAIRS'));
       ```
     * **Scope**: This lock is transaction-scoped; it guarantees mutual exclusion across all concurrent migration executions.
     * **Lifecycle**: Automatically held across the entire migration transaction and automatically released upon `COMMIT` or `ROLLBACK`.
   - **SQLite Implementation & SQLAlchemy Transaction Lifecycle**:
     * In Alembic and SQLAlchemy 2.0, migration contexts manage connections within an active transaction block.
     * **Prohibition of Illegal Nested BEGIN**: Executing `connection.execute(sa.text("BEGIN IMMEDIATE"))` directly inside Alembic fails because Python's DBAPI (`sqlite3`) is already managing a transaction boundary; attempting to issue a raw `BEGIN` raises `OperationalError: cannot start a transaction within a transaction`.
     * **Production-Grade Engine Event Listener Pattern**:
       To enforce immediate write locking and eliminate lock-escalation race conditions on SQLite without violating DBAPI transaction state, revision `0008` hooks into SQLAlchemy's engine `begin` and `connect` events:
       ```python
       import sqlite3
       import sqlalchemy as sa

       # 1. Enforce IMMEDIATE transaction mode on engine begin
       @sa.event.listens_for(engine, "begin")
       def do_sqlite_begin_immediate(conn):
           if conn.dialect.name == "sqlite":
               conn.exec_driver_sql("BEGIN IMMEDIATE")

       # 2. Configure busy timeout and foreign keys on connect
       @sa.event.listens_for(engine, "connect")
       def set_sqlite_pragmas(dbapi_connection, connection_record):
           if isinstance(dbapi_connection, sqlite3.Connection):
               cursor = dbapi_connection.cursor()
               cursor.execute("PRAGMA foreign_keys = ON;")
               cursor.execute("PRAGMA busy_timeout = 30000;")  # 30-second busy timeout
               cursor.close()
       ```
     * **Why This Works**: The `@sa.event.listens_for(engine, "begin")` listener intercepts the transaction initiation *before* the DBAPI emits default deferred `BEGIN`, instructing SQLite directly to acquire a reserved lock. Together with `PRAGMA busy_timeout = 30000;`, concurrent workers wait gracefully up to 30 seconds rather than failing immediately with `database is locked`.
   - **Database Engine Invariant Backstop**:
     * `matching_runs.uq_matching_runs_code UNIQUE (run_code)`
     * `candidate_pairs.uq_cand_pair_legacy_id UNIQUE (legacy_pair_id)`
     * `candidate_pairs.uq_cand_pair_run UNIQUE (matching_run_id, left_source_record_id, right_source_record_id)`
     * `source_records.uq_source_record_key UNIQUE (source_system_id, entity_type, source_key)`

## 3. Rollback Safety & Irreversible Classification (Section 3 Update)

Alembic revisions are strictly classified by their rollback capability:

| Revision ID | Revision Name | Type | Downgrade Capability | Rollback Strategy |
|---|---|---|---|---|
| `0001` | `legacy_staging_rename.py` | Schema DDL | **Safely Reversible** | `downgrade()` renames `legacy_*` back to original names. |
| `0002` | `create_access_control_schema.py` | Schema DDL | **Safely Reversible** | `downgrade()` drops RBAC tables in reverse topological order. |
| `0003` | `create_source_and_intake_schema.py`| Schema DDL | **Safely Reversible** | `downgrade()` drops intake tables in reverse topological order. |
| `0004` | `create_normalization_matching.py` | Schema DDL | **Safely Reversible** | `downgrade()` drops matching tables. |
| `0005` | `create_cluster_review_schema.py` | Schema DDL | **Safely Reversible** | `downgrade()` drops review tables. |
| `0006` | `create_canonical_resolution.py` | Schema DDL | **Safely Reversible** | `downgrade()` drops canonical tables. |
| `0007` | `create_governance_and_export.py` | Schema DDL | **Safely Reversible** | `downgrade()` drops audit and export tables. |
| `0008` | `migrate_legacy_data.py` | **Data Transformation**| **STRICTLY IRREVERSIBLE** | **Automatic downgrade is blocked**. In code: `raise RuntimeError("Automatic downgrade of 0008 is prohibited to prevent lineage loss. Restore from Step 1 physical backup.")`. Rollback must restore Step 1 verified snapshot. |
| `0009` | `seed_initial_governance_data.py` | Seed Data | **Safely Reversible** | `downgrade()` deletes seeded roles, permissions, policy v1. |

---

## 4. Dual-Dialect Compatibility Matrix (PostgreSQL vs SQLite)

| Architectural Feature | PostgreSQL 15+ Target | SQLite 3.x Development / Testing Target | SQLAlchemy Implementation / Abstraction |
|---|---|---|---|
| **UUID Primary Keys** | Native `UUID` (`gen_random_uuid()`) | `CHAR(36)` string format | `TypeDecorator` (`GUIDType`) storing UUID objects as native UUID or hex string. |
| **Payload Storage** | Native `JSONB` with indexing support | Native `JSON` (stored as text with syntax validation) | `sqlalchemy.types.JSON` (automatically selects JSONB on Postgres). |
| **Timezone Timestamps** | `TIMESTAMP WITH TIME ZONE` | ISO-8601 UTC string (`TEXT`) | `DateTime(timezone=True)` with explicit UTC conversion on ingestion. |
| **Foreign Keys** | Always enforced by server engine | Disabled by default; requires PRAGMA | Event listener on connect: `PRAGMA foreign_keys = ON;`. |
| **Temporal Non-Overlap**| `EXCLUDE USING GIST` on `tstzrange` | Triggers (`trg_prevent_membership_temporal_overlap`) | Native DDL on Postgres; SQLite migration script installs triggers. |
| **Partial Unique Indexes**| `CREATE UNIQUE INDEX ... WHERE ...` | Supported in SQLite 3.8+ (`WHERE ...`) | Handled natively by SQLAlchemy `Index(..., postgresql_where=..., sqlite_where=...)`. |
| **Table Alters (DDL)** | Fully transactional `ALTER TABLE` | Limited ALTER TABLE support | Alembic `with op.batch_alter_table(...) as batch_op:`. |
| **Hierarchical Lock** | `pg_advisory_xact_lock` | Database-level write lock | Advisory lock function called in Postgres service layer; SQLite serializes naturally. |

---

## 5. Alembic Revision Roadmap (Phase 2 Delivery)

```text
backend/alembic/versions/
├── 0001_legacy_staging_rename.py           (Renames legacy tables safely to avoid collisions)
├── 0002_create_access_control_schema.py    (users, roles, permissions, user_roles, role_permissions)
├── 0003_create_source_and_intake_schema.py (source_systems, import_batches, source_records, versions, identifiers, runs)
├── 0004_create_normalization_matching.py  (policies, features, candidate_pairs, blocking_paths, evidence)
├── 0005_create_cluster_review_schema.py    (clusters, cluster_members, review_tasks, review_decisions, constraints)
├── 0006_create_canonical_resolution.py     (canonical_entities, memberships, fields, provenance, relationships)
├── 0007_create_governance_and_export.py    (audit_events, retention_policies, deletion_ledger, export_jobs, manifest)
├── 0008_migrate_legacy_data.py             (Transforms and reconciles legacy records; evidence fields remain NULL)
└── 0009_seed_initial_governance_data.py    (Seeds 3 roles, permissions, default VN normalization policy)
```
