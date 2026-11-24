# BACKEND API DOCUMENTATION – W05

## 1. Thông tin dự án

- **Dự án:** AI-13 – CRM Duplicate Detection and Entity Resolution.
- **Milestone:** W05.
- **Module:** Backend API & Matching Integration.
- **Framework:** Python FastAPI.
- **ORM:** SQLAlchemy.
- **Database Development:** SQLite.
- **API Documentation:** Swagger UI / OpenAPI.
- **Testing Framework:** Pytest.

## 2. Mục tiêu triển khai

- Hoàn thiện source FastAPI và tài liệu hướng dẫn tái chạy.
- Khắc phục lỗi route trùng prefix `/api/api/review`.
- Khắc phục lỗi tính điểm tương đồng khi tên pháp lý trống.
- Tích hợp Database với Normalization và Matching Engine.
- Cung cấp Candidate Pairs kèm score, evidence, conflicts và trạng thái Review.
- Kiểm soát trạng thái thành công hoặc thất bại của Matching Pipeline.
- Kiểm thử an toàn luồng Maker–Checker.
- Không bổ sung chức năng tự động merge hoặc writeback CRM.

## 3. Hướng dẫn chạy Backend

### 3.1. Tạo môi trường Python

Thực hiện tại thư mục gốc của project:

    python -m venv venv
    .\venv\Scripts\Activate.ps1

### 3.2. Cài đặt dependencies

    python -m pip install -r requirements.txt

### 3.3. Khởi tạo hoặc cập nhật Database

    python -m alembic upgrade head

Kiểm tra cấu hình DATABASE_URL trước khi thực hiện migration.

Database mặc định của môi trường development:

    sqlite:///./data/songnhat_crm.db

### 3.4. Khởi động FastAPI

    python -m uvicorn main:app --reload

### 3.5. Truy cập API Documentation

- Base URL: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

## 4. Kiến trúc xử lý dữ liệu

Luồng xử lý chính:

CSV Source Data → Intake API → Database Source Records → Normalization Adapter → Matching Engine → Candidate Pairs & Evidence → Candidate API → Manual Review.

Matching Pipeline gồm bốn bước:

| Bước | Phạm vi | Entity Pool |
|---|---|---|
| A-A | CRM_A | ACCOUNT |
| B-B | CRM_B | ACCOUNT |
| A-B | CRM_A và CRM_B | ACCOUNT |
| C-C | CRM_C | CONTACT |

ACCOUNT và CONTACT được xử lý trong các pool riêng biệt.

Normalization Adapter chuyển đổi dữ liệu nguồn thành SourceRecordInput trước khi chuyển sang Matching Engine.

Normalized input hiện được xây dựng trong bộ nhớ. Việc lưu normalized features riêng vào Database cần được xác nhận theo contract của team.

## 5. Danh sách API thuộc phạm vi W05

| Method | Endpoint | Chức năng |
|---|---|---|
| POST | /api/canonical/ingest | Import dữ liệu CSV |
| POST | /api/canonical/match-all | Thực thi Matching Pipeline |
| GET | /api/candidates | Tra cứu Candidate Pairs từ Database |
| GET | /api/review/queue | Tra cứu hàng đợi Review |
| POST | /api/review/tasks/{task_id}/assign | Phân công Review Task |
| POST | /api/review/tasks/{task_id}/release | Giải phóng Review Task |
| GET | /api/review/tasks/{task_id}/proposal | Tra cứu Proposal |
| POST | /api/review/tasks/{task_id}/proposal | Gửi Proposal |
| POST | /api/review/tasks/{task_id}/adjudicate | Xử lý quyết định Review |
| GET | /api/review/clusters/{cluster_id} | Tra cứu Candidate Cluster |
| POST | /api/review/clusters/{cluster_id}/split | Tách Candidate Cluster |
| POST | /api/review/pairs/unlink | Hủy liên kết theo workflow |
| GET | /api/review/conflicts | Tra cứu Conflict |

Danh sách trên tập trung vào các API liên quan đến phạm vi W05, không phải toàn bộ endpoint của project.

## 6. Intake API

**Endpoint:** POST /api/canonical/ingest

**Request Body:**

    {
      "file_path": "data/sample_csv/accounts_source_a.csv",
      "source_code": "CRM_A",
      "entity_pool": "ACCOUNT"
    }

Các bộ dữ liệu mẫu:

| File | Source Code | Entity Pool |
|---|---|---|
| accounts_source_a.csv | CRM_A | ACCOUNT |
| accounts_source_b.csv | CRM_B | ACCOUNT |
| contacts_source.csv | CRM_C | CONTACT |

File path được đọc từ môi trường chạy Backend.

**HTTP Status:**

- 200: Service trả về báo cáo import.
- 400: Phát sinh lỗi trong quá trình import.
- 422: Request không đúng cấu trúc schema.

## 7. Matching Pipeline API

**Endpoint:** POST /api/canonical/match-all

Không yêu cầu Request Body.

API đọc Source Records đang ACTIVE từ Database, thực hiện chuẩn hóa đầu vào và chuyển dữ liệu sang Matching Engine.

Kết quả Matching được lưu vào các bảng liên quan:

- matching_runs
- candidate_pairs
- candidate_pair_evidence

**Response tổng quát:**

    {
      "status": "SUCCESS",
      "report": {
        "pipeline_id": "...",
        "account_internal_a": {},
        "account_internal_b": {},
        "account_cross_ab": {},
        "contact_internal_c": {},
        "total_candidate_pairs": 10,
        "total_duration_seconds": 0.5
      }
    }

Các giá trị trên chỉ mang tính minh họa.

**Quy tắc trạng thái tổng thể:**

| Trạng thái | Ý nghĩa |
|---|---|
| SUCCESS | Cả bốn Matching Run đều COMPLETED |
| FAILED | Có Run thất bại, thiếu kết quả hoặc trạng thái không hợp lệ |
| HELD_CEILING_BREACH | Có Run bị giữ do vượt giới hạn Candidate và không có Run FAILED |

API trả HTTP 200 khi có report, kể cả khi trạng thái nghiệp vụ là FAILED hoặc HELD_CEILING_BREACH.

HTTP 500 được trả khi service phát sinh exception.

Frontend cần kiểm tra cả HTTP status và trường status trong response.

Các Matching Run đã hoàn thành có thể được lưu độc lập. Không cam kết rollback toàn bộ pipeline khi một bước thất bại.

## 8. Candidate Pairs API

**Endpoint:** GET /api/candidates

API đọc kết quả Matching đã lưu trong Database thay cho CSV Preview trước đây.

### 8.1. Query Parameters

| Parameter | Type | Default | Validation |
|---|---|---|---|
| limit | Integer | 50 | 1–200 |
| offset | Integer | 0 | Không âm |
| entity_type | String | null | ACCOUNT hoặc CONTACT |
| matching_run_id | UUID | null | UUID hợp lệ |

Ví dụ:

    GET /api/candidates?limit=10&offset=0

    GET /api/candidates?entity_type=ACCOUNT

    GET /api/candidates?entity_type=CONTACT

### 8.2. Response Fields

| Field | Ý nghĩa |
|---|---|
| data_source | Nguồn dữ liệu DATABASE |
| total_candidates | Tổng số Candidate Pairs phù hợp bộ lọc |
| limit | Giới hạn bản ghi |
| offset | Vị trí phân trang |
| candidates | Danh sách Candidate Pairs |

Mỗi Candidate Pair gồm:

- id
- matching_run_id
- left_source_record_id
- right_source_record_id
- left_source_key
- right_source_key
- entity_pool
- similarity_score
- decision_tier
- proposed_category
- evidence
- conflicts
- review_state
- review_tasks
- created_at

### 8.3. Evidence

Evidence cung cấp thông tin:

- id
- rule_name
- field_name
- similarity_score
- evidence_direction
- evidence_weight
- provenance
- policy_version

Trường evidence_direction hỗ trợ giá trị null theo Database schema.

Conflicts hiện được xác định từ evidence có rule_name là RULE_CONFLICT_DETECTION và evidence_direction là NEGATIVE.

### 8.4. Review State

review_state lấy trạng thái của Review Task mới nhất liên quan đến Candidate Pair.

Nếu chưa có Review Task:

    {
      "review_state": null,
      "review_tasks": []
    }

proposed_category là kết quả đề xuất của Matching, không phải quyết định merge đã được phê duyệt.

API không tự động tạo Review Task hoặc Canonical Membership.

### 8.5. HTTP Status

| Status | Ý nghĩa |
|---|---|
| 200 | Truy vấn thành công |
| 422 | Query parameter không hợp lệ |
| 500 | Lỗi xử lý phía Backend |

Nếu không có dữ liệu phù hợp, API trả HTTP 200 với danh sách candidates rỗng.

### 8.6. Lưu ý tích hợp Frontend

Response của Candidate API đã thay đổi so với CSV Preview.

Frontend cần cập nhật cách đọc evidence, conflicts, pagination và review_state.

Khi không truyền matching_run_id, API có thể trả Candidate Pairs thuộc nhiều Matching Run.

Contract tương thích Frontend cần được xác nhận trước khi tích hợp chính thức.

## 9. Review Workflow

### 9.1. Route Prefix

Prefix cũ bị lỗi:

    /api/api/review/...

Prefix đã sửa:

    /api/review/...

### 9.2. Authentication

Review API sử dụng JWT Bearer Token và cơ chế RBAC.

    Authorization: Bearer YOUR_ACCESS_TOKEN

### 9.3. Maker Proposal

**Endpoint:** POST /api/review/tasks/{task_id}/proposal

Ví dụ Request Body:

    {
      "task_id": "REVIEW_TASK_UUID",
      "decision_type": "DUPLICATE",
      "decision_rationale": "Matching evidence reviewed by Maker"
    }

Các decision_type:

- DUPLICATE
- RELATED
- DISTINCT
- INSUFFICIENT_EVIDENCE

Proposal RELATED yêu cầu relationship_type theo contract hiện tại.

### 9.4. Checker Approval

**Endpoint:** POST /api/review/tasks/{task_id}/adjudicate

Ví dụ Request Body:

    {
      "task_id": "REVIEW_TASK_UUID",
      "action": "APPROVE",
      "adjudication_notes": "Independently reviewed"
    }

Maker và Checker phải là hai người dùng độc lập.

Maker không được tự phê duyệt Proposal của chính mình.

### 9.5. Safety Guardrails

Các test đã xác nhận:

- Proposal không tự động tạo Canonical Entity.
- Proposal không tự động tạo Canonical Membership.
- Approval không tự động tạo Canonical Entity.
- Approval không tự động tạo Canonical Membership.
- Dữ liệu Source Records và Source Record Versions không thay đổi trong luồng được kiểm thử.
- Maker không thể tự phê duyệt.
- Không thể phê duyệt lại Review Task đã được xử lý theo test hiện tại.

Phạm vi kiểm thử trên chưa bao phủ toàn bộ các nhánh Split, Unlink, Reject hoặc hệ thống CRM bên ngoài.

## 10. Matching Validation – Missing Legal Name

### 10.1. Vấn đề

Trong CSV Preview Matcher, việc so sánh hai chuỗi tên rỗng có thể trả độ tương đồng 100%, dẫn đến cộng điểm tên không hợp lệ.

### 10.2. Cách xử lý

- Chuẩn hóa giá trị null và khoảng trắng.
- Chỉ tính độ tương đồng tên khi cả hai giá trị tương ứng đều có nội dung.
- Không cộng điểm tương đồng tên cho dữ liệu tên rỗng.
- Giữ nguyên trọng số và ngưỡng scoring hiện tại.
- Không tự bổ sung quy tắc bắt buộc nhập legal_name.

### 10.3. Contract cần xác nhận

- Legal name có bắt buộc hay không.
- Bản ghi thiếu legal name có được tiếp tục Matching hay không.
- Có được sử dụng Tax ID, Phone và các evidence khác để đánh giá hay không.
- Có cần điều chỉnh trọng số khi thiếu dữ liệu hay không.

Chờ BA xác nhận và QA retest trước khi kết luận hoàn thành validation theo nghiệp vụ.

## 11. Kiểm thử

Chạy toàn bộ test:

    python -m pytest -q

Kết quả ghi nhận tại môi trường development: 50 passed.

| Nhóm kiểm thử | Số test | Kết quả |
|---|---:|---|
| Baseline project | 8 | PASS |
| Review Route | 2 | PASS |
| Matching Validation | 5 | PASS |
| Candidate API | 18 | PASS |
| Matching Integration và Error Handling | 8 | PASS |
| Review Safety | 9 | PASS |
| Tổng cộng | 50 | PASS |

Các file test bổ sung:

- tests/test_review_routes.py
- tests/test_matching_validation.py
- tests/test_candidate_api.py
- tests/test_matching_integration.py
- tests/test_review_safety.py

Database kiểm thử sử dụng SQLite riêng biệt và bật Foreign Key.

Integration Test thực hiện import ba bộ CSV mẫu, chạy Matching Engine và truy vấn Candidate API.

Các test tổng hợp trạng thái Matching thất bại sử dụng report giả lập.

## 12. Giới hạn và vấn đề cần phối hợp

- Chờ BA xác nhận contract xử lý legal_name trống.
- Chờ QA retest các lỗi đã ghi nhận.
- Chờ Frontend xác nhận Candidate API response và Matching status.
- Cần xác nhận yêu cầu lưu normalized_features.
- Chưa kiểm thử toàn bộ nhánh Review.
- Cần cấu hình JWT_SECRET_KEY riêng khi triển khai môi trường thực tế.
- Chưa kiểm chứng writeback đối với hệ thống CRM bên ngoài.
- Endpoint activate-singletons là chức năng có sẵn ngoài phần triển khai mới của W05, cần được đánh giá riêng theo phạm vi nghiệp vụ.

## 13. Kết luận bàn giao

Backend W05 đã triển khai các thay đổi về route, validation kỹ thuật, Database–Matching Integration, Candidate API và xử lý trạng thái Matching Pipeline.

Kết quả kiểm thử tự động ghi nhận 50 test thành công.

Không bổ sung API tự động merge hoặc writeback CRM trong phạm vi thay đổi W05.

Trạng thái bàn giao chính thức phụ thuộc vào Pull Request, code review, xác nhận contract của BA và kết quả QA retest.