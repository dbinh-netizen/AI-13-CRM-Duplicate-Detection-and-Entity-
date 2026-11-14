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

## 4. Quy tắc Nghiệp vụ Bắt buộc (Business Invariants)

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
