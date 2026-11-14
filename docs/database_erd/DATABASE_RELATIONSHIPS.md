# DATABASE RELATIONSHIPS & CARDINALITY SPECIFICATION
## SongNhat CRM Duplicate Detection and Entity Resolution System
### Version: 8.0 – Final Targeted Patch (Candidate Pair Reconciliation, Zero Double-Counting, Source-Specific Import Batches)

---

## 1. Overview of Referential Architecture

Referential integrity in the SongNhat CRM Duplicate Detection and Entity Resolution System is designed around four vital governance rules:
1. **RESTRICT by Default on Identity & Decision Proof**: Deleting core identity records (`source_records`, `review_decisions`, `canonical_entities`) is blocked if dependent evidence or active mappings exist.
2. **Controlled Isolation on Transient Raw Data**: Raw import batches and unparseable rows may only be purged through an authorized retention process (`deletion_ledger`).
3. **Advanced Composite Foreign Keys**: Multi-column foreign keys enforce domain-wide invariants directly at the database engine tier (such as preventing cross-pool matching between Account and Contact, and verifying entity types in hierarchical relationships).
4. **Cross-Batch Lineage Correlation with Batch-Source Parity**: Table `run_sources` links `matching_runs` to `import_batches` via a composite FK `(import_batch_id, source_system_id) REFERENCES import_batches (id, source_system_id)`. This guarantees at the database engine tier that a batch declared in a run manifest strictly matches its authentic source system, while constraint `UNIQUE (matching_run_id, import_batch_id)` allows linking multiple batches from the same source system.

---

## 2. Comprehensive Relationship Matrix (33 Tables)

| # | Parent Table (PK/UK) | Child Table (FK) | Cardinality | ON DELETE Action | Business Rationale & Integrity Rule |
|---|---|---|---|---|---|
| 1 | `users.id` | `user_roles.user_id` | 1 : N | CASCADE | Removing a staging test user removes role assignments. |
| 2 | `roles.id` | `user_roles.role_id` | 1 : N | RESTRICT | A system role cannot be dropped while users are actively assigned. |
| 3 | `roles.id` | `role_permissions.role_id` | 1 : N | CASCADE | Updating role permissions updates mapping table cleanly. |
| 4 | `permissions.id` | `role_permissions.permission_id` | 1 : N | RESTRICT | Built-in permissions cannot be deleted if assigned to roles. |
| 5 | `source_systems.id` | `import_batches.source_system_id` | 1 : N | RESTRICT | Authoritative source systems cannot be deleted if historical batches exist. |
| 6 | `source_systems.(id, entity_type)` | `source_records.(source_system_id, entity_type)` | 1 : N | RESTRICT | **Composite FK**: Enforces intake pool parity; ACCOUNT source system can only originate ACCOUNT records; CONTACT source system can only originate CONTACT records. |
| 7 | `source_records.id` | `source_record_versions.source_record_id` | 1 : N | RESTRICT | Source record identity anchors cannot be dropped; historical versions are protected. |
| 8 | `import_batches.id` | `source_record_versions.import_batch_id` | 1 : N | RESTRICT | An import batch cannot be deleted if referenced by source versions under active retention. |
| 9 | `import_batches.id` | `batch_row_results.import_batch_id` | 1 : N | CASCADE | Quarantine row results follow batch retention schedule. |
| 10 | `source_records.id` | `source_identifiers.source_record_id` | 1 : N | RESTRICT | Prevents loss of tax/national identifiers tied to a master source record. |
| 11 | `source_record_versions.id` | `source_identifiers.source_record_version_id` | 1 : N | RESTRICT | Binds identifier evidence to exact extraction snapshot. |
| 12 | `normalization_policies.id` | `matching_runs.policy_id` | 1 : N | RESTRICT | Normalization policy versions cannot be removed if utilized by historical runs. |
| 13 | `matching_runs.id` | `run_sources.matching_run_id` | 1 : N | CASCADE | Run manifest components are managed atomically with the run. |
| 14 | `source_systems.id` | `run_sources.source_system_id` | 1 : N | RESTRICT | Binds source system to manifest. |
| 15 | `import_batches.(id, source_system_id)` | `run_sources.(import_batch_id, source_system_id)` | 1 : N | RESTRICT | **Composite FK (Batch-Source Parity)**: Guarantees declared source system strictly owns the linked batch; permits multiple batches per system under `UNIQUE (matching_run_id, import_batch_id)`. |
| 16 | `source_record_versions.id` | `normalized_features.source_record_version_id` | 1 : N | RESTRICT | Normalized features cannot be unlinked from their underlying raw version. |
| 17 | `normalization_policies.id` | `normalized_features.normalization_policy_id` | 1 : N | RESTRICT | Preserves policy version governance. |
| 18 | `matching_runs.id` | `candidate_pairs.matching_run_id` | 1 : N | RESTRICT | Historical runs cannot be deleted if candidate pairs exist for review. |
| 19 | `source_records.(id, entity_type)` | `candidate_pairs.(left_source_record_id, entity_type)` | 1 : N | RESTRICT | **Composite FK**: Ensures left record matches pair `entity_type`. |
| 20 | `source_records.(id, entity_type)` | `candidate_pairs.(right_source_record_id, entity_type)` | 1 : N | RESTRICT | **Composite FK**: Ensures right record matches pair `entity_type` (Guarantees Account-Account or Contact-Contact). |
| 21 | `candidate_pairs.id` | `candidate_blocking_paths.candidate_pair_id` | 1 : N | CASCADE | Blocking paths are ancillary metadata belonging to candidate pair. |
| 22 | `candidate_pairs.id` | `candidate_pair_evidence.candidate_pair_id` | 1 : N | CASCADE | Detailed evidence lines belong strictly to the candidate pair lifecycle. |
| 23 | `matching_runs.id` | `candidate_clusters.matching_run_id` | 1 : N | RESTRICT | Clusters cannot be removed independently of run governance. |
| 24 | `candidate_clusters.(id, entity_type)` | `candidate_cluster_members.(candidate_cluster_id, entity_type)` | 1 : N | CASCADE | **Composite FK**: Ensures cluster member entity type matches cluster entity type. |
| 25 | `source_records.(id, entity_type)` | `candidate_cluster_members.(source_record_id, entity_type)` | 1 : N | RESTRICT | **Composite FK**: Prevents enrolling records of different entity types into cluster. |
| 26 | `candidate_pairs.id` | `review_tasks.candidate_pair_id` | 1 : N | RESTRICT | Candidate pair cannot be purged if review task is active. |
| 27 | `review_tasks.id` | `review_decisions.review_task_id` | 1 : N | RESTRICT | Review task cannot be deleted once formal decision records are logged. |
| 28 | `candidate_pairs.id` | `review_decisions.candidate_pair_id` | 1 : N | RESTRICT | Protects candidate pair evidence behind a completed decision. |
| 29 | `users.id` | `review_decisions.proposed_by` | 1 : N | RESTRICT | Data Steward user identity is immutable in decision history. |
| 30 | `users.id` | `review_decisions.approved_by` | 1 : N | RESTRICT | Approver user identity is immutable in decision history. |
| 31 | `review_decisions.id` | `review_decisions.superseded_by` | 1 : 1 (Self) | RESTRICT | Self-referencing link for decision reversals / splits. |
| 32 | `source_records.id` | `pair_decision_constraints.left_source_record_id` | 1 : N | RESTRICT | Protected negative constraints (DISTINCT memory). |
| 33 | `source_records.id` | `pair_decision_constraints.right_source_record_id` | 1 : N | RESTRICT | Protected negative constraints (DISTINCT memory). |
| 34 | `review_decisions.id` | `pair_decision_constraints.established_by_decision_id` | 1 : N | RESTRICT | Binds negative constraint directly to approving decision. |
| 35 | `users.id` | `canonical_entities.created_by` | 1 : N | RESTRICT | Entity creator provenance. |
| 36 | `canonical_entities.(id, entity_type)` | `canonical_memberships.(canonical_entity_id, entity_type)` | 1 : N | RESTRICT | **Composite FK**: Ensures canonical entity type matches membership entity type. |
| 37 | `source_records.(id, entity_type)` | `canonical_memberships.(source_record_id, entity_type)` | 1 : N | RESTRICT | **Composite FK**: Guarantees source record and canonical master share identical entity type. |
| 38 | `source_record_versions.(id, source_record_id)` | `canonical_memberships.(source_record_version_id, source_record_id)` | 1 : N | RESTRICT | **Composite FK**: Guarantees that the membership's version belongs to that source record. |
| 39 | `review_decisions.(id, approved_by)` | `canonical_memberships.(decision_id, approved_by)` | 1 : N | RESTRICT | **Composite FK**: Ensures membership approver strictly matches review decision approver. |
| 40 | `canonical_entities.id` | `canonical_fields.canonical_entity_id` | 1 : N | CASCADE | Canonical golden profile fields belong to the canonical entity. |
| 41 | `canonical_fields.id` | `canonical_field_provenance.canonical_field_id` | 1 : N | CASCADE | Provenance detail cascades if field definition is retired. |
| 42 | `source_records.id` | `canonical_field_provenance.source_record_id` | 1 : N | RESTRICT | Source origin of canonical value cannot be deleted. |
| 43 | `canonical_entities.(id, entity_type)` | `entity_relationships.(from_canonical_id, from_entity_type)` | 1 : N | RESTRICT | **Composite FK**: Binds origin endpoint and enforces entity type integrity. |
| 44 | `canonical_entities.(id, entity_type)` | `entity_relationships.(to_canonical_id, to_entity_type)` | 1 : N | RESTRICT | **Composite FK**: Binds destination endpoint and enforces entity type integrity. |
| 45 | `review_decisions.(id, approved_by)` | `entity_relationships.(decision_id, approved_by)` | 1 : N | RESTRICT | **Composite FK**: Ensures relationship approver strictly matches review decision approver. |
| 46 | `users.id` | `audit_events.actor_id` | 1 : N | RESTRICT | User accounts cannot be removed from audit trail. |
| 47 | `review_decisions.id` | `audit_events.related_decision_id` | 1 : N | RESTRICT | Binds audit log to formal review decision. |
| 48 | `users.id` | `deletion_ledger.approved_by` | 1 : N | RESTRICT | Erasure and retention executions require immutable approver stamp. |
| 49 | `export_jobs.id` | `export_manifest_items.export_job_id` | 1 : N | CASCADE | Manifest items belong strictly to export job. |
| 50 | `canonical_entities.id` | `export_manifest_items.canonical_entity_id` | 1 : N | RESTRICT | Exported entities are protected from deletion. |
| 51 | `source_records.id` | `export_manifest_items.source_record_id` | 1 : N | RESTRICT | Exported crosswalk items trace directly to source record. |
| 52 | `canonical_memberships.id` | `export_manifest_items.canonical_membership_id` | 1 : N | RESTRICT | Allows identifying which exports are affected when a membership is later superseded. |

---

## 3. Entity Relationships: Cycle Detection, Concurrency & Scope

### 3.1. Self-Loop Prevention
- The database constraint `CHECK (from_canonical_id <> to_canonical_id)` on `entity_relationships` strictly prevents 1-hop self-loops (e.g. Entity A being its own parent).

### 3.2. Relationship Entity Type Compatibility
- Enforced by composite FKs to `canonical_entities (id, entity_type)` and the database constraint `chk_rel_type_entity_compat`:
  - `PARENT_OF`, `BRANCH_OF`, `SITE_OF`: Strictly requires `from_entity_type = 'ACCOUNT'` and `to_entity_type = 'ACCOUNT'`.
  - `AFFILIATED_WITH`: Permits `CONTACT -> ACCOUNT`, `ACCOUNT -> ACCOUNT`, and `CONTACT -> CONTACT`.

### 3.3. Multi-hop Cycle Detection & Concurrency Serialization
- **Hierarchical Relationships (`PARENT_OF`, `BRANCH_OF`, `SITE_OF`)**:
  - Must conform to a **Directed Acyclic Graph (DAG)** / Tree.
  - Multi-hop cycles (e.g. A -> B -> A or A -> B -> C -> A) cannot be caught by static SQL `CHECK` constraints.
  - **Concurrency Race Condition**: If Transaction 1 inserts A -> B while Transaction 2 concurrently inserts B -> A, both queries running recursive CTE checks simultaneously would see no cycle and both commit, creating an illegal cycle.
  - **PostgreSQL Serialization Mechanism**:
    Before executing the recursive cycle validation query and edge insert, transactions modifying hierarchical relationships must acquire a transaction-scoped advisory lock:
    ```sql
    SELECT pg_advisory_xact_lock(hashtext('hierarchy_dag_lock'));
    ```
    This serializes DAG updates at the database tier without locking unrelated business tables.
  - **Recursive Cycle Validation Query**:
    ```sql
    WITH RECURSIVE ancestor_tree AS (
        SELECT to_canonical_id AS node
        FROM entity_relationships
        WHERE from_canonical_id = NEW.to_canonical_id
          AND relationship_type IN ('PARENT_OF', 'BRANCH_OF', 'SITE_OF')
          AND status = 'ACTIVE'
        UNION ALL
        SELECT r.to_canonical_id
        FROM entity_relationships r
        INNER JOIN ancestor_tree t ON r.from_canonical_id = t.node
        WHERE r.relationship_type IN ('PARENT_OF', 'BRANCH_OF', 'SITE_OF')
          AND r.status = 'ACTIVE'
    )
    SELECT 1 FROM ancestor_tree WHERE node = NEW.from_canonical_id;
    ```
    If this query returns a row, inserting the relationship would form a closed cycle; the transaction is aborted with an integrity error.
- **Affiliation Relationships (`AFFILIATED_WITH`)**:
  - Represents non-hierarchical, professional or partnership connections (e.g. a Contact affiliated with multiple Companies, or cross-company alliances).
  - DAG restrictions and serialization advisory locks are **explicitly not applied** to `AFFILIATED_WITH`, permitting bidirectional or multi-path affiliations without error.
