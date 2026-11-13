# Dự án AI-13: CRM Duplicate Detection & Entity Resolution (SongNhat)

Khung mã nguồn gốc (Base Repository) thống nhất cho toàn bộ thành viên nhóm AI-13. Dự án được tổ chức theo đúng các phân hệ yêu cầu của SongNhat, tích hợp sẵn Giao diện Web, Backend API, Thuật toán so khớp và Cơ sở dữ liệu.

---

## 1. Công nghệ sử dụng (Tech Stack)

- **Backend & REST API:** Python 3.12 + FastAPI + Uvicorn + Pydantic (`backend/`, `main.py`).
- **Chuẩn hóa dữ liệu & Thuật toán AI:** Pandas + RapidFuzz + Unicodedata (`backend/services/`).
- **Cơ sở dữ liệu (Database):** SQLAlchemy ORM — Mặc định tự động khởi tạo **SQLite** (`data/songnhat_crm.db`) khi chạy code để mọi máy đều chạy được ngay; hỗ trợ **PostgreSQL 15** qua `docker-compose.yml`.
- **Giao diện (Frontend):** HTML5 + Tailwind CSS + JavaScript Fetch API (`frontend/`).
- **Kiểm thử tự động (Testing):** Pytest (`tests/`).

---

## 2. Cấu trúc thư mục & Phân chia vị trí làm việc cho cả nhóm

Mỗi thành viên chỉ làm việc trong đúng thư mục được phân công để tránh xung đột code (Conflict) khi gộp nhánh trên GitHub:

```text
AI-13-CRM-Duplicate-Detection-and-Entity-/
├── backend/
│   ├── config.py                       # Cấu hình ngưỡng điểm (65% / 85%), giới hạn 200,000 cặp
│   ├── database.py                     # Kết nối Database tự động (SQLite / PostgreSQL)
│   ├── models.py                       # [NHÓM DATABASE] Khai báo các bảng dữ liệu (ERD)
│   ├── schemas.py                      # Định dạng dữ liệu JSON đầu vào / đầu ra cho API
│   ├── api/
│   │   └── routes.py                   # [NHÓM BACKEND API] Các đường dẫn API (/api/records, /api/candidates...)
│   └── services/
│       ├── intake.py                   # [NHÓM DATA] Đọc 3 nguồn CSV & kiểm tra dữ liệu đầu vào
│       ├── normalizer.py               # [NHÓM DATA] Chuẩn hóa tiếng Việt, SĐT (+84 -> 0), Mã số thuế
│       ├── matcher.py                  # [NHÓM AI MATCHING] Thuật toán Blocking & chấm điểm tương đồng
│       ├── resolver.py                 # [NHÓM BACKEND] Duyệt 2 cấp độc lập (Steward -> Approver) & Tách/Gộp
│       └── exporter.py                 # [NHÓM BACKEND] Xuất bảng định danh chuẩn Crosswalk CSV
│
├── frontend/
│   ├── index.html                      # [NHÓM UI DASHBOARD] Giao diện Tổng quan CRM, Danh sách & Import
│   └── duplicate_review.html           # [NHÓM UI REVIEW] Giao diện Đối chiếu & Duyệt cặp nghi trùng
│
├── data/
│   └── sample_csv/                     # [NHÓM BA & DATA] Chứa 3 file CSV chuẩn (2 Doanh nghiệp + 1 Cá nhân)
│       ├── accounts_source_a.csv
│       ├── accounts_source_b.csv
│       └── contacts_source.csv
│
├── docs/                               # [TÀI LIỆU BÁO CÁO CỦA NHÓM]
│   ├── business_requirements/          # Lưu tài liệu phân tích nghiệp vụ
│   ├── database_erd/                   # Lưu sơ đồ ERD & thiết kế cơ sở dữ liệu
│   ├── test_plans/                     # Lưu kịch bản kiểm thử (Test Plan & Test Cases)
│   └── ui_designs/                     # Lưu bản thiết kế giao diện mẫu
│
├── tests/
│   └── test_matching_pipeline.py       # [NHÓM QA/TEST] Kịch bản kiểm thử tự động bằng Pytest
│
├── main.py                             # File khởi chạy toàn bộ hệ thống (Web + API)
├── requirements.txt                    # Danh sách thư viện Python cài đặt chung
├── docker-compose.yml                  # Cấu hình chạy PostgreSQL bằng Docker
└── README.md                           # Tài liệu hướng dẫn chung cho cả nhóm
```
