# Dự án SongNhat CRM – Duplicate Detection & Entity Resolution System

Hệ thống Phát hiện Trùng lặp & Giải quyết Danh tính Thực thể trong CRM dành cho Công ty SongNhat (Phase 2 – Implementation).

---

## 1. Công nghệ sử dụng (Technology Stack)

- **Backend & REST API:** Python 3.12 + FastAPI + Uvicorn + Pydantic v2 (`backend/`, `main.py`).
- **ORM & Database Migration:** SQLAlchemy 2.0 + Alembic (`backend/alembic/`).
- **Chuẩn hóa dữ liệu & Thuật toán Khớp:** Pandas 2.2+ + RapidFuzz 3.10+ + Unicodedata (`backend/services/`).
- **Cơ sở dữ liệu (Database Engines):**
  * **PostgreSQL 15+ (Môi trường Staging & Production):** Quản lý qua Docker Compose (`docker-compose.yml`) với cơ chế khóa `pg_advisory_xact_lock` và chỉ mục `GiST`.
  * **SQLite 3.x (Môi trường Local Dev & Fast Testing):** Tự động khởi tạo tại `data/songnhat_crm.db`, hỗ trợ triggers bảo đảm temporal integrity và hook `BEGIN IMMEDIATE`.
- **Giao diện người dùng (Frontend):** HTML5 + Tailwind CSS + JavaScript Fetch API (`frontend/`).
- **Kiểm thử tự động (Testing Framework):** Pytest 8.3+ (`tests/`, `pytest.ini`).

---

## 2. Cấu trúc Thư mục Dự án (Phase 2 Architecture)

```text
AI-13-CRM-Duplicate-Detection-and-Entity-/
├── .env.example                     # Biến môi trường mẫu
├── .gitignore                       # Cấu hình bỏ qua git
├── CONTRIBUTING.md                  # Hướng dẫn đóng góp & Git workflow
├── docker-compose.yml               # Cấu hình container PostgreSQL 15
├── pytest.ini                       # Cấu hình Pytest (pythonpath = .)
├── README.md                        # Hướng dẫn cài đặt & vận hành
├── requirements.txt                 # Danh mục thư viện phụ thuộc Python
├── main.py                          # Điểm khởi chạy ứng dụng FastAPI
│
├── backend/                         # Backend Source Code
│   ├── config.py                    # Cấu hình hệ thống & ngưỡng điểm
│   ├── database.py                  # Khởi tạo SQLAlchemy Engine & Session
│   ├── alembic/                     # Quản lý migration cơ sở dữ liệu (Revisions 0001 - 0009)
│   ├── models/                      # Khai báo 33 bảng thực thể theo thiết kế Phase 1
│   ├── schemas/                     # Pydantic Schemas cho API
│   ├── security/                    # Xác thực JWT & phân quyền RBAC
│   ├── services/                    # Các engine nghiệp vụ:
│   │   ├── intake_engine.py         # Kiểm tra & nạp 3 nguồn CSV, định tuyến Quarantine
│   │   ├── normalizer_engine.py     # Chuẩn hóa Unicode, SĐT, Mã số thuế, Email
│   │   ├── matching_engine.py       # Multi-path blocking & chấm điểm tương đồng
│   │   ├── review_engine.py         # Quy trình duyệt 2 cấp Maker-Checker
│   │   ├── canonical_engine.py      # Quản lý thực thể chuẩn tắc & liên kết thời gian
│   │   └── export_engine.py         # Xuất bảng định danh Crosswalk & Manifest
│   └── api/                         # RESTful API Endpoints
│
├── frontend/                        # Giao diện Web
│   ├── index.html                   # Dashboard tổng quan & nhập liệu
│   └── duplicate_review.html        # Giao diện đối chiếu & duyệt cặp nghi trùng
│
├── data/                            # Dữ liệu mẫu & Database cục bộ
│   ├── sample_csv/                  # 3 file CSV đầu vào (CRM_A, CRM_B, CRM_C)
│   │   ├── accounts_source_a.csv    # ERP_NORTH (Account)
│   │   ├── accounts_source_b.csv    # CRM_SOUTH (Account)
│   │   ├── contacts_source.csv      # WEB/ZALO (Contact)
│   │   └── ground_truth_pairs.csv   # Dữ liệu nhãn kiểm chứng
│   └── songnhat_crm.db              # File SQLite database cục bộ
│
├── docs/                            # Hồ sơ Thiết kế & Đặc tả Phase 1
│   └── database_erd/                # 9 tài liệu thiết kế chuẩn mực đã đồng bộ
│
└── tests/                           # Bộ kiểm thử tự động
    ├── conftest.py                  # Fixtures cơ sở dữ liệu & người dùng mẫu
    └── test_matching_pipeline.py    # Kiểm thử luồng matching & quy tắc Maker-Checker
```

---

## 3. Hướng dẫn Cài đặt & Khởi chạy (Quick Start)

### 3.1. Yêu cầu hệ thống:
- Python 3.12+ (khuyến nghị Python 3.12.5).
- Git.
- Docker & Docker Compose (tùy chọn, chỉ cần khi chạy PostgreSQL).

### 3.2. Cài đặt môi trường:
```bash
# 1. Clone repository
git clone <REPO_URL>
cd AI-13-CRM-Duplicate-Detection-and-Entity-

# 2. Tạo và kích hoạt môi trường ảo (Virtual Environment)
python -m venv venv
# Trên Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Trên Linux/macOS/Git Bash:
source venv/bin/activate

# 3. Cài đặt các gói phụ thuộc
pip install -r requirements.txt

# 4. Thiết lập file biến môi trường
cp .env.example .env
```

### 3.3. Khởi chạy Database:
- **Tùy chọn A (Mặc định – SQLite cho Local Dev):**
  Không cần cài đặt thêm server. Hệ thống tự động sử dụng `data/songnhat_crm.db`.
- **Tùy chọn B (PostgreSQL qua Docker Compose):**
  ```bash
  docker-compose up -d postgres
  ```

### 3.4. Chạy ứng dụng Backend (FastAPI):
```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```
- Truy cập Swagger API Documentation: `http://127.0.0.1:8000/docs`
- Truy cập Giao diện Dashboard: `http://127.0.0.1:8000/`
- Truy cập Giao diện Đối chiếu Trùng lặp: `http://127.0.0.1:8000/review`

### 3.5. Chạy Kiểm thử tự động (Testing):
```bash
# Chạy toàn bộ test suite
pytest

# Chạy test kèm thông tin chi tiết
pytest -v
```

---

## 4. W04 — Exact Matching Interface

- Contract đầu vào: danh sách normalized records; hàm công khai `generate_exact_candidate_pairs(records)` cũng nhận raw records và tự chuẩn hóa.
- Contract đầu ra: `{total_records, total_candidates, candidates}`; mỗi candidate gồm `left_source_key`, `right_source_key`, `entity_pool`, `similarity_score`, `proposed_category`, `reasons`, `conflicts`, `review_state`.
- Exact matching: `GET /api/candidates/exact`.
- Fuzzy matching: mặc định tắt; `enable_fuzzy=False` trong `compare_pair`.
- Integration fixture: xem `test_exact_candidate_pair_fixture` trong `tests/test_matching_pipeline.py`.

> Người phụ trách `main.py` và `database.py` kiểm tra lại các lệnh trên trên một máy sạch rồi cập nhật nếu khác.

---

## 5. Quy tắc Nghiệp vụ Bắt buộc (Business Invariants)

1. **Phân lập Entity Pool:**
   - Account: So sánh trong nội bộ nguồn và giữa CRM_A với CRM_B.
   - Contact: So sánh độc lập trong CRM_C.
   - Tuyệt đối **không so sánh chéo** giữa Account và Contact.
2. **Quy tắc Maker-Checker (No Self-Approval):**
   - Data Steward (Maker): Tạo đề xuất gộp hoặc tách.
   - Approver (Checker): Phê duyệt hoặc từ chối đề xuất độc lập.
   - Ràng buộc tầng cơ sở dữ liệu: `proposed_by <> approved_by`.
3. **Bảo tồn Bằng chứng Thô (Immutable Raw Evidence):**
   - Giá trị gốc từ CSV không bao giờ bị ghi đè bởi giá trị chuẩn hóa.
   - Truy vết xuất xứ qua `import_batches`, `source_record_versions`, và `audit_events`.
4. **Không Cắt ngọn mờ ám (No Silent Truncation):**
   - Tối đa 200.000 candidate pairs mỗi full run; vượt ngưỡng kích hoạt cờ `ceiling_breached = TRUE`.

---

## 6. Phân công theo vai trò (10 thành viên)

Danh sách việc **thay đổi mỗi tuần** nên nằm trên Jira, không ghi vào README. Bảng dưới chỉ ghi vị trí và thư mục phụ trách, ít thay đổi. Người phụ trách điền tên GitHub vào cột cuối.

| Vị trí (tag Jira) | Việc chính | Thư mục / file | Người phụ trách |
|---|---|---|---|
| PM | Chia thẻ KAN mỗi tuần, theo dõi tiến độ, giữ `main` ổn định | Jira, `README.md`, `CONTRIBUTING.md` | `@...` |
| BA | Phân tích nghiệp vụ, bảng đối chiếu yêu cầu RFP | `docs/business_requirements/` | `@...` |
| DB | Thiết kế ERD và bảng dữ liệu | `backend/models.py`, `backend/database.py`, `docs/database_erd/` | `@...` |
| DATA | Đọc CSV, kiểm tra dữ liệu, chuẩn hóa tiếng Việt | `backend/services/intake.py`, `normalizer.py`, `data/sample_csv/` | `@...` |
| AI | Khớp chính xác và khớp mờ, chấm điểm, tạo cặp ứng viên | `backend/services/matcher.py` | `@...` |
| BE (2 người) | API, duyệt hai cấp, xuất crosswalk, phân quyền | `backend/api/`, `schemas.py`, `services/resolver.py`, `exporter.py`, `security.py` | `@...`, `@...` |
| FE - Dashboard | Giao diện tổng quan, danh sách, nhập CSV | `frontend/index.html` | `@...` |
| FE - Review | Giao diện đối chiếu và duyệt cặp nghi trùng | `frontend/duplicate_review.html` | `@...` |
| QA | Kế hoạch kiểm thử, test tự động, bộ đáp án | `tests/`, `docs/test_plans/`, `data/sample_csv/ground_truth_pairs.csv` | `@...` |

### Làm việc hằng tuần với Jira
1. Đầu tuần, PM tạo thẻ mới tên `[Wxx][ROLE] Việc cần làm`, mô tả theo mẫu trong `CONTRIBUTING.md` (có ghi rõ file/thư mục làm việc).
2. Thành viên xem thẻ của vai trò mình trên bảng Jira, tạo nhánh `feature/KAN-xx-ten-ngan` từ `main`, làm xong mở Pull Request.
3. Thiết kế giao diện mẫu (KAN-8) nằm ở `docs/ui_designs/crm_dashboard_prototype.html`.

---

## 7. Quy tắc làm việc chung

- Không push thẳng lên `main`. Mỗi task Jira một nhánh `feature/KAN-xx-ten-ngan`, mở Pull Request, **người khác duyệt** rồi mới merge.
- Thẻ Jira: mở PR thì chuyển **In Review**, merge xong mới chuyển **Done**.
- Chi tiết xem `CONTRIBUTING.md`.
- Repo **public**: chỉ dùng dữ liệu mẫu do nhóm tự tạo (tên, SĐT, mã số thuế đều giả). Không commit `.env`, `venv/`, `__pycache__/`, `data/*.db`.

---

## 8. Dữ liệu mẫu và đáp án

- `data/sample_csv/ground_truth_pairs.csv` ghi đáp án các cặp đã gán nhãn để đo precision và recall. Cột: `pair_id,record_a,record_b,label,note`.
- `label` nhận một trong bốn giá trị: `duplicate` (cùng thực thể), `related` (liên quan nhưng khác nhau), `distinct` (khác nhau), `insufficient` (chưa đủ bằng chứng).
- Phân quyền và quy tắc không tự duyệt: `backend/security.py`.
