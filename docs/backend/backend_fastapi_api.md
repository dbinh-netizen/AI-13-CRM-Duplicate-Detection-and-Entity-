
# AI-13 — Tài liệu Backend FastAPI

## 1. Giới thiệu

Tài liệu mô tả các API Backend FastAPI được triển khai
trong nhiệm vụ Jira W03.

### Phạm vi thực hiện

- Tiếp nhận dữ liệu từ file CSV.
- Lưu dữ liệu đầu vào vào Database.
- Tra cứu danh sách bản ghi nguồn.
- Xem chi tiết dữ liệu gốc và thông tin metadata.
- Xem trước các cặp bản ghi có khả năng trùng lặp.
- Kiểm tra dữ liệu đầu vào và xử lý lỗi API.

### Ngoài phạm vi

- Tự động hợp nhất bản ghi (auto-merge).
- Ghi ngược dữ liệu vào hệ thống CRM nguồn.
- Thay đổi cấu trúc Database của nhóm.
- Thay đổi thuật toán Matching của nhóm.

## 2. Hướng dẫn chạy Backend

Mở terminal tại thư mục gốc của dự án.

### Bước 1: Kích hoạt môi trường Python

```powershell
.\venv\Scripts\Activate.ps1
```

### Bước 2: Cài đặt thư viện

```powershell
python -m pip install -r requirements.txt
```

### Bước 3: Chuẩn bị Database

Cấu hình kết nối Database theo thiết lập của dự án
và chạy các migration cần thiết trước khi sử dụng API.

### Bước 4: Khởi động FastAPI

```powershell
python -m uvicorn main:app --reload
```

Đường dẫn sử dụng:

- FastAPI: http://127.0.0.1:8000
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI JSON: http://127.0.0.1:8000/openapi.json

## 3. Danh sách API

### 3.1. API tiếp nhận dữ liệu

**Endpoint:** POST /api/canonical/ingest

**Chức năng:** Đọc file CSV, kiểm tra dữ liệu và lưu
các bản ghi hợp lệ vào Database.

Request mẫu:

```json
{
  "file_path": "data/sample_csv/accounts_source_a.csv",
  "source_code": "ERP_NORTH",
  "entity_pool": "ACCOUNT"
}
```

Kết quả thành công: HTTP 200.

Response chứa trạng thái SUCCESS và báo cáo import,
bao gồm số bản ghi hợp lệ, bị cách ly và bị từ chối.

Lưu ý: file_path là đường dẫn file mà Backend có thể
truy cập, không phải chức năng upload file từ trình duyệt.

### 3.2. API tra cứu danh sách bản ghi nguồn

**Endpoint:** GET /api/v1/source-records

**Chức năng:** Truy vấn các bản ghi nguồn đã được lưu
trong Database.

Tham số:

- limit: Số bản ghi mỗi trang, từ 1 đến 200.
  Mặc định là 50.
- offset: Vị trí bắt đầu lấy dữ liệu, tối thiểu là 0.
- entity_type: Lọc theo ACCOUNT hoặc CONTACT.

Ví dụ:

GET /api/v1/source-records?limit=50&offset=0&entity_type=ACCOUNT

Response HTTP 200 có cấu trúc:

```json
{
  "total": 3,
  "limit": 50,
  "offset": 0,
  "records": []
}
```

Lưu ý: records là mảng chứa dữ liệu thực tế.
Mảng rỗng ở ví dụ trên chỉ minh họa cấu trúc response.

### 3.3. API xem chi tiết bản ghi nguồn

**Endpoint:** GET /api/v1/source-records/{record_id}

**Chức năng:** Tra cứu bản ghi theo UUID.

Response thành công HTTP 200 bao gồm:

- record: Thông tin bản ghi và dữ liệu gốc.
- source_system: Thông tin hệ thống nguồn.
- import_batch: Thông tin đợt import.
- version: Phiên bản dữ liệu nguồn mới nhất.
- normalized_fields: Các trường đã chuẩn hóa,
  nếu dữ liệu chuẩn hóa đã tồn tại.

Trường hợp không tìm thấy bản ghi: HTTP 404.

```json
{
  "detail": {
    "code": "SOURCE_RECORD_NOT_FOUND",
    "message": "Source record not found"
  }
}
```

UUID không hợp lệ: HTTP 422.

### 3.4. API xem trước các cặp ứng viên trùng lặp

**Endpoint:** GET /api/candidates

**Chức năng:** Xem trước các cặp bản ghi có khả năng
trùng lặp được tạo từ dữ liệu CSV mẫu.

Lưu ý:

- API hiện sử dụng dữ liệu CSV.
- Chưa truy vấn bảng candidate_pairs trong Database.
- Chỉ phục vụ demo và kiểm thử tích hợp.
- Không tự động hợp nhất dữ liệu.
- Không ghi ngược vào CRM nguồn.

## 4. Kiểm thử API

Chạy lệnh:

```powershell
python -m pytest tests/ -v
```

Kết quả kiểm thử đã xác nhận:

**7 bài kiểm thử thành công.**

Nội dung kiểm thử:

- Kiểm tra API Intake.
- Kiểm tra lưu bản ghi vào Database.
- Kiểm tra API danh sách bản ghi nguồn.
- Kiểm tra API chi tiết bản ghi nguồn.
- Kiểm tra UUID không hợp lệ.
- Kiểm tra tham số phân trang không hợp lệ.
- Kiểm tra bản ghi không tồn tại.

API Candidate Preview đã được kiểm thử thủ công
và trả về HTTP 200.

## 5. Lưu ý kỹ thuật

- Backend chính sử dụng Python FastAPI.
- Không phụ thuộc Node.js khi khởi động.
- Truy vấn Database thông qua SQLAlchemy.
- Sử dụng các model Database hiện có của nhóm.
- normalized_fields có thể rỗng nếu chưa có
  dữ liệu từ quy trình chuẩn hóa.
- Không bổ sung API auto-merge hoặc writeback
  vào CRM nguồn trong nhiệm vụ này.
- Các chức năng Matching, Review và Canonical
  có sẵn ngoài phạm vi thay đổi của nhiệm vụ.

## 6. Thành phần bàn giao

- Mã nguồn Backend FastAPI.
- API Intake và Source Records.
- Candidate Preview.
- Swagger/OpenAPI.
- Tài liệu hướng dẫn API.
- Bộ kiểm thử pytest.
- Git commit và Pull Request.
```
