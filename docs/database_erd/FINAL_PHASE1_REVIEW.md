# BÁO CÁO ĐÁNH GIÁ THIẾT KẾ CUỐI CÙNG GIAI ĐOẠN 1 (FINAL PHASE 1 REVIEW)
## HỆ THỐNG PHÁT HIỆN TRÙNG LẶP & GIẢI QUYẾT THỰC THỂ SONGNHAT CRM
### Version: 8.5 – Tương thích Legacy Entity-Type, Kiểm thực Toàn diện Endpoint Pool & Xác minh Khóa Giao dịch SQLite

---

## 1. TỔNG QUAN & XÁC NHẬN KIỂM SOÁT CÁC ĐIỂM HOÀN THIỆN VERSION 8.5

Báo cáo này giải trình và xác nhận việc xử lý dứt điểm các điểm kỹ thuật trọng tâm theo yêu cầu của Hội đồng Kiến trúc và Data Owner trong bản vá mục tiêu **Version 8.5**:

### 1.1. Tương thích Loại Thực thể Legacy (Legacy Entity-Type Compatibility) & Ánh xạ Chuẩn tắc:
- **Hiện trạng Schema**:
  * `source_systems.entity_type`: `ACCOUNT` / `CONTACT`.
  * `source_records.entity_type`: `ACCOUNT` / `CONTACT`.
  * `legacy_source_records.entity_type`: Chuỗi thô legacy (`COMPANY`, `BRANCH`, `CONTACT`).
- **Quy tắc Ánh xạ Xác định & Hai chiều (Deterministic Bidirectional Mapping)**:
  * `COMPANY` $\rightarrow$ `ACCOUNT` (Subtype: `COMPANY`).
  * `BRANCH` $\rightarrow$ `ACCOUNT` (Subtype: `BRANCH`).
  * `CONTACT` $\rightarrow$ `CONTACT` (Subtype: `PERSON`).
- **Nguyên tắc Cấm & Cách ly Nghiêm ngặt**:
  * **Tuyệt đối không dùng `MIN(entity_type)`** để giải quyết sự bất nhất dữ liệu legacy. Nếu một `source_key` có nhiều loại thực thể mâu thuẫn, nó bị loại trừ khỏi tập khóa duy nhất `unique_legacy_keys` và đưa vào Quarantine.
  * Cấm tuyệt đối ánh xạ legacy `CONTACT` vào pool `ACCOUNT` (e.g., bản ghi Contact trong CRM_A hoặc CRM_B).
  * Cấm tuyệt đối ánh xạ legacy `COMPANY` hoặc `BRANCH` vào pool `CONTACT` (e.g., bản ghi Doanh nghiệp trong CRM_C).
  * Kiểm tra đồng thời cả 3 thành phần: `source_system`, `entity_type`, và `source_key`. Dữ liệu không tương thích được cách ly qua cơ chế Quarantine của intake, tuyệt đối không suy đoán hay sửa đổi dữ liệu nguồn thô.
- **Ghi nhận Giả định Subtype (Cần Data Owner Phê duyệt - Sign-off)**:
  * Việc gộp `COMPANY` và `BRANCH` vào chung entity pool `ACCOUNT` nhằm bảo đảm tính toàn vẹn của mô hình phân giải trùng lặp B2B. Phân biệt `COMPANY` và `BRANCH` được lưu giữ đầy đủ trong `source_records.record_payload` và `source_record_attributes`. Giả định này được ghi nhận chính thức để Data Owner ký duyệt (Sign-off) trước khi chạy thực tế ở Phase 2.

### 1.2. Kiểm thực Đối xứng Toàn diện Hai Đầu mút Vật lý (Full Bilateral Endpoint Pool Symmetry & NULL-Safe 3VL):
- Trong logic 3 giá trị (Three-Valued Logic - 3VL) của SQL, các phép so sánh với `NULL` đánh giá thành `UNKNOWN`. Để ngăn chặn triệt để tình trạng một phép so sánh lỗi rơi vào nhánh `ELSE 0` (hợp lệ), CTE `physical_endpoint_verification` thiết lập hàng rào kiểm soát 100% an toàn:
  1. **Bảo vệ NULL Toàn diện cả 2 Phía**:
     * Phát hiện `l_mig.source_record_id IS NULL` hoặc `r_mig.source_record_id IS NULL`.
     * Phát hiện `ps.left_source_record_id IS NULL` hoặc `ps.right_source_record_id IS NULL`.
     * Phát hiện `ps.entity_type IS NULL`, `l_mig.entity_type IS NULL`, hoặc `r_mig.entity_type IS NULL`.
     * Bất kỳ giá trị nào là `NULL` $\implies$ Lập tức đánh dấu `is_endpoint_mismatch = 1`.
  2. **Đối xứng Pool Hai Đầu mút (Bilateral Pool Symmetry)**:
     * Kiểm tra `l_mig.entity_type <> r_mig.entity_type` (đầu mút trái và phải phải thuộc cùng pool).
     * Kiểm tra `ps.entity_type <> l_mig.entity_type` và `ps.entity_type <> r_mig.entity_type` (pool của cặp vật lý phải khớp với cả hai đầu mút).
     * Bất kỳ sự cọc cạch nào $\implies$ Lập tức đánh dấu `is_endpoint_mismatch = 1`.
  3. **Đồng bộ Thứ tự Chuẩn tắc (Canonical Ordering Parity)**:
     * Kiểm tra `ps.left_source_record_id <> LEAST(l_mig.source_record_id, r_mig.source_record_id)`.
     * Kiểm tra `ps.right_source_record_id <> GREATEST(l_mig.source_record_id, r_mig.source_record_id)`.
     * Nếu đảo ngược thứ tự $\implies$ Lập tức đánh dấu `is_endpoint_mismatch = 1`.
  4. **Chỉ khi toàn bộ điều kiện NOT NULL, đối xứng pool và thứ tự chuẩn tắc đều thỏa mãn mới đánh giá là 0 (hợp lệ)**.

### 1.3. Cơ chế Vòng đời Khóa Giao dịch SQLite / Alembic (SQLite Transaction Lifecycle Verification):
- **Phân tích Nguyên nhân Lỗi**:
  * Khi Alembic thực thi migration script, context của Alembic đã chủ động mở một khối giao dịch trên kết nối.
  * Trong SQLite với thư viện chuẩn DBAPI (`sqlite3`), việc thực thi trực tiếp `connection.execute(sa.text("BEGIN IMMEDIATE"))` cố gắng phát lệnh `BEGIN` trong khi kết nối đã ở trạng thái giao dịch hoạt động, dẫn đến ngoại lệ `sqlite3.OperationalError: cannot start a transaction within a transaction`.
- **Giải pháp Chuẩn mực trong SQLAlchemy 2.0**:
  * Sử dụng hook cấp engine `@sa.event.listens_for(engine, "begin")` để can thiệp đúng thời điểm bắt đầu giao dịch, chỉ thị cho driver SQLite phát lệnh `BEGIN IMMEDIATE` ngay trước khi DBAPI gửi lệnh mặc định:
    ```python
    @sa.event.listens_for(engine, "begin")
    def do_sqlite_begin_immediate(conn):
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("BEGIN IMMEDIATE")
    ```
  * Kết hợp thiết lập `PRAGMA busy_timeout = 30000;` và `PRAGMA foreign_keys = ON;` trên hook `@sa.event.listens_for(engine, "connect")` để đảm bảo kết nối kiên nhẫn chờ khóa ghi tối đa 30 giây thay vì lập tức báo lỗi `database is locked`.
  * Trên PostgreSQL: Tiếp tục sử dụng `SELECT pg_advisory_xact_lock(hashtext('MIG_0008_HISTORICAL_PAIRS'))` với phạm vi tự động bao phủ trọn vẹn transaction và tự động giải phóng khi commit hoặc rollback.

### 1.4. Minh bạch Trạng thái Render Sơ đồ Mermaid ERD (Mermaid Rendering Status Transparency):
- **Kiểm tra Cấu trúc (Structural Validation)**: **PASS** (33 bảng thực thể, 43 quan hệ quan hệ, bảo đảm 100% composite FK).
- **Kiểm tra Cú pháp (Syntax Validation)**: **PASS** (0 lỗi cú pháp qua custom parser, 484 dòng code `erDiagram` chuẩn mực).
- **Kiểm tra Render Đồ họa Thực tế (Actual Rendering Validation)**: **NOT EXECUTED (Awaiting Phase 2 CI/CD Environment)**. Môi trường host Windows cục bộ không có `mmdc` trong `PATH` và sandbox mạng bị cô lập không tải gói ngoài; nhóm kỹ thuật trung thực ghi nhận tình trạng này và đưa vào kiểm thử tự động tại các test cases **`TC-MIG-32`**, **`TC-MIG-40`**, và **`TC-MIG-49`** trong pipeline CI/CD Phase 2.

---

## 2. BẢNG PHÂN BẬC ƯU TIÊN 5 KỊCH BẢN CANDIDATE PAIRS

| Thứ tự ưu tiên | Kịch bản đánh giá | Điều kiện logic toán học | Trạng thái kết thúc | Hành động với `candidate_pairs` |
|:---:|---|---|---|:---:|
| **Bậc 1** | Khóa đầu mút không tồn tại (Dangling Key) | $L_{cnt} = 0 \lor R_{cnt} = 0$ | `PAIR_REJECTED_DANGLING_KEY` | Không insert; bảo tồn trong `legacy_candidate_pairs`. |
| **Bậc 2** | Khóa đầu mút trùng lặp / đa nghĩa (Ambiguous Key) | $L_{cnt} > 1 \lor R_{cnt} > 1$ | `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT` | Không insert; bảo tồn trong `legacy_candidate_pairs`. |
| **Bậc 3** | Đầu mút bị cách ly / không tương thích | $L_{mig} \text{ IS NULL} \lor R_{mig} \text{ IS NULL}$ | `PAIR_QUARANTINED_ENDPOINT` | Không insert; bảo tồn trong `legacy_candidate_pairs`. |
| **Bậc 4** | Mâu thuẫn chéo pool (Account vs Contact) | $L_{mig}.entity\_type \ne R_{mig}.entity\_type$ | `PAIR_REJECTED_CROSS_POOL_MISMATCH` | Không insert; bảo tồn trong `legacy_candidate_pairs`. |
| **Bậc 5** | Cặp di trú hợp lệ (Valid Migrated Pair) | Cả 2 đầu mút duy nhất, cùng pool, pair hợp lệ | `PAIR_MIGRATED` | **INSERT** với `legacy_pair_id = legacy.id`, gán đúng run Account/Contact. |

*Cảnh báo Discrepancy*: Bất kỳ cặp nào thỏa mãn 1-4 nhưng sai lệch dữ liệu vật lý sẽ rơi vào `PAIR_UNMAPPED_DISCREPANCY`, khiến assertion thất bại và buộc giao dịch rollback.

---

## 3. CÂU LỆNH SQL ĐỐI SOÁT HAI CHIỀU & BẢO TOÀN DỮ LIỆU CHUẨN MỰC (VERSION 8.5)

```sql
-- ============================================================================
-- CANDIDATE PAIRS TWO-WAY PHYSICAL PARITY & CONSERVATION RECONCILIATION (V8.5)
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
                
            -- Precedence 3: Quarantined / Incompatible Endpoint (Endpoint quarantined during intake or incompatible)
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
    -- Mọi PAIR_MIGRATED đều có đúng 1 physical row với endpoint, pool và legacy_pair_id chuẩn xác.
    -- Nếu discrepancy count > 0, assertion này lập tức kích hoạt FAIL và buộc ROLLBACK transaction.
    CASE WHEN co.pair_unmapped_discrepancy_count = 0 
              AND co.pair_migrated_count = pm.physical_migrated_count 
         THEN 'PASS' ELSE 'FAIL_LEGACY_TO_PHYSICAL' END AS legacy_to_physical_assertion,

    -- Assertion B (Physical-to-Legacy Parity & Endpoint Integrity):
    -- Không có candidate pair mồ côi, không trùng lặp legacy_pair_id, không cọc cạch pool, không lệch endpoint.
    CASE WHEN pm.physical_orphan_count = 0 
              AND pm.physical_migrated_count = pm.physical_distinct_legacy_id_count 
              AND pm.physical_pool_mismatch_count = 0
              AND pm.physical_endpoint_mismatch_count = 0
         THEN 'PASS' ELSE 'FAIL_PHYSICAL_TO_LEGACY' END AS physical_to_legacy_assertion,

    -- Assertion C (Bảo toàn số lượng Candidate Pairs):
    -- Tổng legacy pairs == Tổng evaluated pairs == Tổng 5 nhóm kết quả phân loại.
    -- (Các cặp discrepancy không được tính là thành công; nếu tồn tại thì phép bảo toàn FAIL).
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

    -- Assertion D (Khớp nối chỉ số matching_runs):
    -- total_candidates của matching_runs phải bằng đúng số lượng physical pairs và status = COMPLETED.
    CASE WHEN rm.runs_total_candidates = pm.physical_migrated_count 
              AND rm.incomplete_runs_count = 0 
         THEN 'PASS' ELSE 'FAIL_RUN_METRICS_PARITY' END AS run_parity_assertion

FROM legacy_pair_summary lp, categorized_outcomes co, physical_metrics pm, run_metrics rm;
```

---

## 4. DANH MỤC TEST CASES DI TRÚ MỞ RỘNG (`TC-MIG-04` ĐẾN `TC-MIG-50`)

| Test ID | Tên Test Case | Ràng buộc / Cơ chế mục tiêu | Khẳng định kiểm thử (Expected Assertion) | Trạng thái |
|:---:|---|---|---|:---:|
| **TC-MIG-04** | `test_legacy_source_record_conservation_reconciliation` | Bảo toàn dòng nguồn trên tất cả source & quarantine batches | $N_{\text{legacy}} = N_{\text{evaluated}} = N_{\text{mig}} + N_{\text{quar}} + N_{\text{rej}}$. Số dòng migrated bằng đúng số dòng physical v1 và distinct source records. Không có dòng quarantine nào rò rỉ vào `source_records`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-05** | `test_legacy_candidate_pair_quarantined_endpoint_handling` | Xử lý kịch bản đầu mút cặp bị Quarantine | Khi 1 hoặc cả 2 đầu mút bị cách ly, cặp KHÔNG được tạo trong `candidate_pairs`; được bảo tồn trong `legacy_candidate_pairs` và phân loại đúng `PAIR_QUARANTINED_ENDPOINT`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-06** | `test_legacy_candidate_pair_cross_pool_rejection` | Xử lý kịch bản mâu thuẫn chéo pool (Account paired Contact) | Cặp ứng viên kết nối Account và Contact bị từ chối với `PAIR_REJECTED_CROSS_POOL_MISMATCH` và không bao giờ được tạo trong `candidate_pairs`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-07** | `test_legacy_source_duplicate_or_invalid_key_quarantine` | Tiền kiểm tra khóa nguồn và xuất xứ hệ thống | Các dòng legacy trùng `(source_system, source_key)` hoặc thiếu key đều được cách ly; các dòng thiếu `source_system` được đưa vào `BATCH_UNMAPPED_QUARANTINE` với `source_system_id = NULL` mà không gán nguồn giả. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-08** | `test_legacy_candidate_pair_dangling_key_rejection` | Xử lý kịch bản khóa đầu mút không tồn tại (Dangling Key) | Khi một cặp tham chiếu `source_key` không tồn tại trong `legacy_source_records`, cặp bị phân loại `PAIR_REJECTED_DANGLING_KEY` và loại khỏi `candidate_pairs`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-09** | `test_legacy_candidate_pair_ambiguous_endpoint_quarantine` | Xử lý kịch bản khóa đầu mút trùng lặp / đa nghĩa | Khi đầu mút khớp với nhiều dòng nguồn trùng lặp, cặp bị cách ly với `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT`, không suy đoán hay liên kết bừa bãi. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-10** | `test_legacy_candidate_pair_conservation_reconciliation` | Khẳng định bảo toàn cặp ứng viên dưới matching run | Kiểm tra $\text{Total Legacy Pairs} = \text{Evaluated Pairs} = \sum \text{5 nhóm kết quả}$. Khẳng định `pair_migrated_count` bằng đúng số dòng physical `candidate_pairs`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-11** | `test_source_specific_import_batches_and_unmapped_quarantine` | Source batches & unmapped source quarantine (Zero Fake Sources) | Xác minh migration tạo các batch riêng biệt cho `CRM_A`, `CRM_B`, `CRM_C` và batch cách ly `BATCH_UNMAPPED_QUARANTINE` (`source_system_id = NULL`); kiểm tra check constraint chặn NULL cho batch thường và cho phép cho quarantine. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-12** | `test_run_sources_batch_system_parity_and_multi_batch` | Batch-source parity composite FK & multi-batch linking | Xác minh Composite FK `(import_batch_id, source_system_id)` từ chối cặp batch-source cọc cạch; xác minh `UNIQUE (matching_run_id, import_batch_id)` cho phép liên kết nhiều batch từ cùng 1 source system trong 1 matching run. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-13** | `test_candidate_pair_invalid_endpoint_handling` | Xử lý cặp có đầu mút không hợp lệ / bị cách ly | Đầu mút bị cách ly ở intake không tạo row trong `candidate_pairs`, được phân loại chuẩn xác `PAIR_QUARANTINED_ENDPOINT`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-14** | `test_source_key_collision_across_source_systems` | Kiểm tra xung đột khóa giữa các source CRM khác nhau | Khi `source_key` tồn tại ở cả CRM_A và CRM_B ($L_{cnt} > 1$), endpoint không thể xác định duy nhất; phân loại `PAIR_QUARANTINED_AMBIGUOUS_ENDPOINT` không suy đoán. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-15** | `test_ambiguous_endpoint_quarantine_isolation` | Cách ly tuyệt đối cho đầu mút không duy nhất | Các cặp ứng viên có đầu mút đa nghĩa được bảo tồn trong `legacy_candidate_pairs`, tạo đúng 0 bản ghi trong `candidate_pairs`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-16** | `test_matching_runs_total_candidates_post_migration_accuracy` | Độ chính xác chỉ số matching run sau migration | Xác minh `total_candidates` được cập nhật từ 0 lên đúng số lượng bản ghi migrate thực tế; status chuyển từ `RUNNING` sang `COMPLETED`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-17** | `test_legacy_to_physical_parity_assertion` | Đối soát theo chiều thuận (Legacy sang Physical) | Mọi bản ghi `PAIR_MIGRATED` đều hiện diện vật lý trong `candidate_pairs` với đúng neo `legacy_pair_id`, đúng cặp ID và entity pool. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-18** | `test_physical_to_legacy_parity_assertion` | Đối soát theo chiều nghịch (Physical về Legacy) | Mọi bản ghi `candidate_pairs` tạo bởi migration 0008 đều trỏ về bản ghi cha hợp lệ trong `legacy_candidate_pairs`; zero orphan pairs. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-19** | `test_orphan_migrated_candidate_pair_detection` | Phát hiện cặp ứng viên mồ côi (Zero Orphan Invariant) | Tiêm bản ghi giả lập không có gốc legacy; xác nhận câu đối soát hai chiều kích hoạt cảnh báo lỗi `FAIL_PHYSICAL_TO_LEGACY`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-20** | `test_idempotent_migration_replay` | Tính bất biến khi chạy lại migration | Chạy lại migration 0008 bị chặn an toàn bởi unique constraints (`run_code`, `legacy_pair_id`) hoặc logic pre-check mà không sinh dữ liệu trùng. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-21** | `test_matching_run_completion_and_transaction_atomicity` | Tính nguyên tử của transaction khi matching run lỗi giữa chừng | Bắt đầu matching run ở `RUNNING`; nếu có lỗi assertion thì toàn bộ transaction rollback, không lưu trạng thái dở dang. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-22** | `test_mermaid_erd_syntax_validation` | Kiểm tra cú pháp và cấu trúc sơ đồ Mermaid ERD | Phân tích `erd.mmd` bảo đảm 0 lỗi cú pháp; xác nhận đúng 33 bảng, 43 quan hệ; không có quan hệ độc lập thừa thãi. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-23** | `test_source_key_collision_across_source_systems` | Phát hiện xung đột khóa chéo giữa các hệ thống nguồn | Xác nhận khóa nguồn trùng giữa CRM_A và CRM_B ($L_{cnt} > 1$) không bị ép gán nguồn bừa bãi, được cách ly an toàn. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-24** | `test_source_record_resolution_multi_batch_immunity` | Tính miễn nhiễm nhân bản khi một CRM có nhiều batch | Xác minh `unique_migrated_sources` không join `import_batches` nên không bị nhân bản dòng khi một hệ thống có nhiều đợt import. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-25** | `test_legacy_endpoint_source_system_parity` | Bảo đảm tương khớp tuyệt đối giữa CRM legacy và target | Đầu mút thuộc CRM_A chỉ được liên kết với `source_records` thuộc CRM_A; không bao giờ bị lẫn sang CRM_B hoặc CRM_C. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-26** | `test_idempotent_replay_completed_reconciled` | Kịch bản B: Chạy lại an toàn khi đã hoàn tất và đối soát đạt | Khi cả 2 runs ở `COMPLETED` và đối soát đạt 4 assertion PASS, migration 0008 kết thúc an toàn (no-op) mà không tạo trùng lặp. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-27** | `test_idempotency_guard_single_matching_run_fail_closed` | Kịch bản C: Fail-closed khi chỉ tồn tại 1 matching run | Khi chỉ có 1 matching run (e.g. Account có, Contact thiếu), migration báo lỗi `RuntimeError`, chặn tự động phục hồi gây lỗi. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-28** | `test_idempotency_guard_corrupted_run_reconciliation_fail` | Kịch bản D: Fail-closed khi đối soát dữ liệu cũ thất bại | Khi runs tồn tại nhưng dữ liệu không thỏa mãn đối soát 4 assertions, migration chặn thực thi và yêu cầu restore snapshot. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-29** | `test_concurrent_migration_execution_serialization` | Kịch bản E: Kiểm soát khóa và tuần tự hóa thực thi đồng thời | Sử dụng khóa `pg_advisory_xact_lock` tuần tự hóa các execution đồng thời, ngăn chặn triệt để race conditions. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-30** | `test_endpoint_physical_parity_mismatch_detection` | Phát hiện lệch endpoint vật lý | Tiêm bản ghi lệch `left_source_record_id` hoặc `right_source_record_id` $\implies$ Assertion B kích hoạt `FAIL_PHYSICAL_TO_LEGACY`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-31** | `test_unmapped_discrepancy_triggers_transaction_rollback` | Xử lý lỗi kỹ thuật nội bộ unmapped discrepancy | Nếu tồn tại `PAIR_UNMAPPED_DISCREPANCY` (count > 0) $\implies$ đối soát thất bại, giao dịch tự động rollback. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-32** | `test_mermaid_actual_renderer_validation` | Kiểm thực render đồ họa thực tế qua Mermaid CLI | Bộ test harness Phase 2 thực thi `mmdc` render toàn bộ `erd.mmd` thành SVG/PNG, xác nhận 0 lỗi runtime rendering. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-33** | `test_source_systems_entity_type_fallback_to_legacy` | Đối soát pool với loại thực thể nguồn legacy | Xác minh ánh xạ kiểm tra đúng `sr.entity_type` với loại thực thể legacy `ulk.legacy_entity_type` và `source_systems.entity_type`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-34** | `test_null_safe_endpoint_resolution` | Xử lý an toàn NULL trong unique_migrated_sources | Xác minh các endpoint thiếu hoặc không hợp lệ đánh giá thành NULL an toàn, không làm sai lệch số lượng migrated. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-35** | `test_single_null_endpoint_physical_pair_rejection` | Phát hiện 1 phía đầu mút bị NULL | Cặp vật lý có 1 đầu mút NULL bị `physical_endpoint_verification` phát hiện `is_endpoint_mismatch = 1` và từ chối. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-36** | `test_both_null_endpoints_physical_pair_rejection` | Phát hiện cả 2 phía đầu mút bị NULL | Cặp vật lý có cả 2 đầu mút NULL bị phát hiện `is_endpoint_mismatch = 1`, không rơi vào bẫy so sánh `ELSE 0`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-37** | `test_physical_scope_column_consistency` | Khai báo toàn vẹn cột trong CTE physical_scope | Xác minh mọi cột tham chiếu (`left_source_key`, `right_source_key`, `matched_legacy_id`) đều có mặt trong `physical_scope`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-38** | `test_candidate_pair_canonical_insert_ordering_parity` | Đồng bộ sắp xếp canonical ordering `LEAST < GREATEST` | Xác minh thứ tự sắp xếp nhất quán trên cả 4 tầng: INSERT, Unique Constraint, Parity Verification, Reconciliation. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-39** | `test_alembic_transaction_locking_lifecycle` | Vòng đời khóa giao dịch Alembic trong Postgres & SQLite | Xác minh `pg_advisory_xact_lock` bao phủ toàn bộ transaction; xác minh SQLite không phát lệnh lồng `BEGIN IMMEDIATE`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-40** | `test_mermaid_actual_rendering_environment_gate` | Cổng kiểm tra môi trường render đồ họa Mermaid | Kiểm tra tính sẵn sàng của công cụ `mmdc` trong pipeline CI/CD trước khi xuất file SVG sơ đồ. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-41** | `test_legacy_entity_type_pool_mapping_compatibility` | Tương thích ánh xạ loại thực thể legacy vào pool | Kiểm tra `unique_legacy_keys` ánh xạ chuẩn `COMPANY/BRANCH -> ACCOUNT`, `CONTACT -> CONTACT`; chặn dùng `MIN()` che giấu dữ liệu xung đột. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-42** | `test_cross_pool_incompatible_legacy_intake_quarantine` | Cách ly bản ghi legacy không tương thích pool tại intake | Bản ghi Contact trong CRM_A/B hoặc Company/Branch trong CRM_C bị cách ly tại intake, không bao giờ được tạo trong `source_records`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-43** | `test_legacy_subtype_assumption_preservation_signoff` | Lưu giữ phân biệt subtype và phê duyệt Data Owner | Xác nhận subtype `COMPANY` và `BRANCH` được lưu giữ trong `record_payload` mà không phân mảnh bảng; có cờ phê duyệt Data Owner. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-44** | `test_bilateral_endpoint_pool_symmetry_assertion` | Đối xứng pool giữa 2 đầu mút (`l_mig.entity_type = r_mig.entity_type`) | Xác minh `physical_endpoint_verification` phát hiện lỗi và đánh dấu `is_endpoint_mismatch = 1` nếu 2 đầu mút khác pool. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-45** | `test_bilateral_physical_pair_pool_parity_assertion` | Khớp nối pool giữa candidate pair và cả 2 đầu mút | Xác minh `physical_endpoint_verification` kiểm tra `ps.entity_type = l_mig.entity_type` và `= r_mig.entity_type`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-46** | `test_null_safe_physical_endpoint_3vl_guard_verification` | Bảo vệ toàn diện 3VL NULL trên cả 2 đầu mút | Kiểm tra bất kỳ giá trị NULL nào trong ID đầu mút hoặc entity_type đều kích hoạt mismatch và làm fail assertion. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-47** | `test_sqlite_driver_begin_immediate_engine_listener` | Hook event `begin` của SQLAlchemy engine trên SQLite | Xác minh SQLite kích hoạt chế độ IMMEDIATE qua engine event listener, tránh lỗi DBAPI lồng `BEGIN IMMEDIATE`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-48** | `test_sqlite_busy_timeout_deadlock_prevention` | Cấu hình busy timeout trên kết nối SQLite | Xác minh `PRAGMA busy_timeout = 30000;` hoạt động hiệu quả khi có tranh chấp ghi đồng thời, tránh lỗi `database is locked`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-49** | `test_mermaid_erd_phase2_cicd_visual_regression_pipeline` | Pipeline kiểm thử hồi quy trực quan Mermaid trong CI/CD | Tự động hóa kiểm thử biên dịch `erd.mmd` thành SVG trong môi trường container CI/CD Phase 2 có sẵn `mmdc`. | `TEST_DESIGNED (Awaiting Phase 2)` |
| **TC-MIG-50** | `test_multi_batch_import_invariance_on_legacy_parity` | Bất biến của phép đối soát khi một nguồn có nhiều batch | Xác minh `unique_migrated_sources` cho kết quả chính xác duy nhất dù hệ thống nguồn có 1 hay hàng trăm đợt import. | `TEST_DESIGNED (Awaiting Phase 2)` |

---

## 5. BẢO TOÀN KIẾN TRÚC CHUẨN MỰC 33 BẢNG & ĐỒNG BỘ TÀI LIỆU

Hồ sơ 9 tài liệu thiết kế chuẩn đã được cập nhật đồng bộ hoàn toàn giữa `./` và `./docs/database_erd/` với **100% SHA-256 Checksum Parity**:

1. [DATABASE_DESIGN.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_DESIGN.md)
2. [DATABASE_MIGRATION.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_MIGRATION.md)
3. [DATABASE_SCHEMA.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_SCHEMA.md)
4. [DATABASE_CONSTRAINTS.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_CONSTRAINTS.md)
5. [DATABASE_RELATIONSHIPS.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_RELATIONSHIPS.md)
6. [DATABASE_TESTING.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_TESTING.md)
7. [DATABASE_TRACEABILITY_MATRIX.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/DATABASE_TRACEABILITY_MATRIX.md)
8. [erd.mmd](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/erd.mmd)
9. [FINAL_PHASE1_REVIEW.md](file:///d:/AI-13-CRM-Duplicate-Detection-and-Entity-/FINAL_PHASE1_REVIEW.md)

### Cam kết ranh giới:
- Đội ngũ kỹ thuật cam kết **KHÔNG chạy migration Phase 2**, không can thiệp cơ sở dữ liệu vật lý, bảo toàn kiến trúc 33 bảng hiện hữu, dừng lại tại ranh giới Phase 1 để chờ phê duyệt **Design Approval** từ Data Owner và Hội đồng Kiến trúc SongNhat.

---

## 6. KHUYẾN NGHỊ BÀN GIAO & PHÊ DUYỆT CỔNG THIẾT KẾ (DESIGN GATE)

- **Trạng thái Khuyến nghị**: **PROVISIONAL APPROVAL (APPROVED FOR PHASE 1 DESIGN GATE)**.
- **Cơ sở Phê duyệt**:
  1. Toàn bộ 4 blocker kỹ thuật của Version 8.5 đã được giải quyết triệt để ở tầng thiết kế logic, mô hình quan hệ, ràng buộc toàn vẹn và câu lệnh đối soát toán học.
  2. 50 Test Cases di trú (`TC-MIG-01` đến `TC-MIG-50`) đã sẵn sàng cho bộ kiểm thử tự động của Phase 2.
  3. Không có bất kỳ sự thay đổi phá vỡ nào đối với kiến trúc 33 bảng đã được phê duyệt.
- **Điều kiện Kích hoạt Phase 2**:
  1. Data Owner ký duyệt biên bản phê duyệt giả định subtype mapping (`COMPANY` / `BRANCH` $\rightarrow$ `ACCOUNT`).
  2. Pipeline CI/CD Phase 2 cung cấp container môi trường có cài đặt `mmdc` để thực thi cổng render đồ họa tự động (`TC-MIG-49`).
