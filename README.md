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

---

## 3. Cách chạy nhanh (Windows, Git Bash)

Yêu cầu: Git, Python 3.12. Docker Desktop chỉ cần nếu muốn dùng PostgreSQL.

```bash
git clone <URL-REPO>
cd <TÊN-REPO>
python -m venv venv
source venv/Scripts/activate        # PowerShell: venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload           # hoặc: python main.py (nếu main.py đã có uvicorn.run)
```

Mở http://127.0.0.1:8000/docs để xem và thử API. Mặc định hệ thống tự tạo SQLite tại `data/songnhat_crm.db`. Chạy kiểm thử: `pytest`.

> Người phụ trách `main.py` và `database.py` kiểm tra lại các lệnh trên trên một máy sạch rồi cập nhật nếu khác.

---

## 4. Phân công theo vai trò (10 thành viên)

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

## 5. Quy tắc làm việc chung

- Không push thẳng lên `main`. Mỗi task Jira một nhánh `feature/KAN-xx-ten-ngan`, mở Pull Request, **người khác duyệt** rồi mới merge.
- Thẻ Jira: mở PR thì chuyển **In Review**, merge xong mới chuyển **Done**.
- Chi tiết xem `CONTRIBUTING.md`.
- Repo **public**: chỉ dùng dữ liệu mẫu do nhóm tự tạo (tên, SĐT, mã số thuế đều giả). Không commit `.env`, `venv/`, `__pycache__/`, `data/*.db`.

---

## 6. Dữ liệu mẫu và đáp án

- `data/sample_csv/ground_truth_pairs.csv` ghi đáp án các cặp đã gán nhãn để đo precision và recall. Cột: `pair_id,record_a,record_b,label,note`.
- `label` nhận một trong bốn giá trị: `duplicate` (cùng thực thể), `related` (liên quan nhưng khác nhau), `distinct` (khác nhau), `insufficient` (chưa đủ bằng chứng).
- Phân quyền và quy tắc không tự duyệt: `backend/security.py`.
