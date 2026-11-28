# Tài liệu Chuẩn hóa Môi trường & Kiểm chứng Tích hợp Hệ thống (W05)

## 1. Đối chiếu cấu hình với Tech Stack & Contract W04
- **Backend:** Python + FastAPI (chạy qua `uvicorn`, base path `/api/v1`).
- **Database:** PostgreSQL 15 (`postgres:15-alpine` qua Docker Compose) cho môi trường tích hợp/kiểm thử; hỗ trợ SQLite (`sqlite:///./data/songnhat_crm.db`) cho kiểm thử nhanh cục bộ.
- **Tham số nghiệp vụ chuẩn hóa theo W04:**
  - `MAX_ROWS_PER_FILE=5000` (tối đa 5.000 dòng/file CSV, tổng 3 file tối đa 15.000 dòng).
  - `CANDIDATE_CEILING=200000` (trần số cặp ứng viên mỗi lần chạy detection).
  - `FRESHNESS_THRESHOLD_BUSINESS_DAYS=2` (ngưỡng độ mới dữ liệu).
- **Bảo mật:** Tuyệt đối không đưa file `.env` thật, mật khẩu/secret thật, hoặc dữ liệu CRM thật lên repository. Chỉ sử dụng `.env.example` và dữ liệu mẫu/fixture kiểm thử.

## 2. Yêu cầu Dependencies
- Docker & Docker Compose v2+
- Python 3.11+
- Các thư viện Python trong `requirements.txt` (FastAPI, Uvicorn, SQLAlchemy/Psycopg, Pytest, v.v.).

## 3. Hướng dẫn khởi động môi trường tích hợp
### Bước 1: Tạo biến môi trường
```bash
cp .env.example .env
```
*(Nếu chạy FastAPI trực tiếp trên máy host thay vì trong container, sửa `POSTGRES_HOST=localhost` và `DATABASE_URL=postgresql://crm_user:crm_password_change_me@localhost:5432/songnhat_crm_db` trong file `.env`).*

### Bước 2: Khởi động PostgreSQL
```bash
docker compose up -d
docker compose ps
```
Kiểm tra container `songnhat_crm_postgres` đạt trạng thái `Up (healthy)`.

### Bước 3: Cài đặt dependencies & khởi động Backend FastAPI
```bash
python -m venv .venv
source .venv/bin/activate   # Trên Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
*(Lưu ý: Kiểm tra đúng module entrypoint của FastAPI trong repo như `app.main:app` hoặc `src.main:app`).*

## 4. Hướng dẫn QA chạy lại kiểm thử
1. Đảm bảo PostgreSQL đang chạy (`docker compose ps` -> `healthy`).
2. Chạy toàn bộ bộ test:
   ```bash
   pytest -v
   ```
3. Kiểm tra luồng API tích hợp theo W04 qua Swagger UI (`http://localhost:8000/docs`) hoặc `curl`:
   - `POST /api/v1/runs` (tải lên `manifest.json` kèm 3 file `accounts_a.csv`, `accounts_b.csv`, `contacts.csv`).
   - `POST /api/v1/runs/{run_id}/detections` và `GET /api/v1/detections/{detection_id}`.
   - `GET /api/v1/runs/{run_id}/candidates` và `GET /api/v1/candidates/{candidate_id}`.

## 5. Xử lý lỗi môi trường thường gặp & Khôi phục
- **Lỗi xung đột cổng (`port 5432 is already allocated`):**
  - Nguyên nhân: Máy đã có PostgreSQL chạy sẵn ở cổng 5432.
  - Khắc phục: Đổi `POSTGRES_PORT=5433` trong `.env` và cập nhật cổng tương ứng trong `DATABASE_URL`, sau đó chạy lại `docker compose up -d`.
- **Backend báo lỗi không kết nối được Database (`Connection refused`):**
  - Nguyên nhân: Container Postgres chưa khởi tạo xong hoặc sai `POSTGRES_HOST` (`localhost` vs `postgres`).
  - Khắc phục: Kiểm tra `docker exec -it songnhat_crm_postgres pg_isready -U crm_user -d songnhat_crm_db` trả về `accepting connections` và đối chiếu lại `DATABASE_URL` trong `.env`.
- **Lỗi dữ liệu cũ / schema lệch giữa các lần test:**
  - Khắc phục: Khôi phục môi trường sạch bằng lệnh:
    ```bash
    docker compose down -v
    docker compose up -d
    ```
- **Lỗi thiếu biến môi trường hoặc sai kiểu dữ liệu:**
  - Khắc phục: Đối chiếu lại từng khóa giữa `.env` và `.env.example`, đảm bảo không để trống `SECRET_KEY` và `DATABASE_URL`.
