# Quy tắc làm việc chung

## 1. Git
- `main` luôn phải chạy được. **Không push thẳng lên `main`.**
- Mỗi task Jira = một nhánh: `feature/KAN-15-exact-match`, `fix/KAN-17-import-error`, `docs/KAN-10-test-plan`.
- Commit ghi mã Jira ở đầu: `KAN-15: thêm khớp chính xác theo SĐT`.
- Trước khi push: `git pull --rebase origin main`, chạy thử lại, rồi `git push -u origin <nhánh>`.
- Mở Pull Request vào `main`, tên `[KAN-15] ...`. **Người khác duyệt, không tự duyệt PR của mình** (đúng tinh thần RFP REV 03).

## 2. Jira
- Mỗi tuần PM tạo thẻ mới tên `[Wxx][ROLE] Việc cần làm` (ROLE: PM, BA, DB, DATA, AI, BE, FE, QA). Danh sách việc nằm trên Jira, **không ghi vào README**.
- Bắt đầu làm: To Do → In Progress. Mở PR: sang **In Review** (dán link PR vào thẻ). PR đã merge vào `main`: sang **Done**. Không có code hay tài liệu trên `main` thì không chuyển Done.
- Nếu Jira đã kết nối GitHub (thẻ có mục Development), đặt mã KAN trong tên nhánh, commit và PR thì Jira tự gắn link. Chưa kết nối thì nhờ PM bật.
- Mẫu mô tả thẻ (PM điền khi tạo):
  ```
  Mục tiêu: ...
  Tiêu chí hoàn thành: ...
  File/thư mục làm việc: backend/services/matcher.py
  Phụ thuộc: KAN-xx (nếu có)
  Hạn: ...
  ```

## 3. Definition of Done
- [ ] Chạy được theo README trên máy sạch (hoặc có hướng dẫn chạy riêng cho phần của mình)
- [ ] Có test hoặc ví dụ chạy kèm kết quả mong đợi
- [ ] Không có dữ liệu thật, mật khẩu, `.env`
- [ ] Cập nhật tài liệu liên quan (README, docs/)
- [ ] PR đã được duyệt và merge

## 4. Dữ liệu
Chỉ dùng `data/sample_csv/` do nhóm tự tạo. Tên cột và schema các file CSV chốt trong `docs/database_erd`; muốn đổi phải báo cả nhóm.

## 5. Thay đổi cấu trúc
Không tự ý đổi tên hay di chuyển thư mục. Cần đổi thì hỏi trong nhóm trước, rồi làm bằng một PR riêng.

## 6. Nhịp làm việc
Họp nhanh 10 phút mỗi ngày: hôm qua xong gì, hôm nay làm gì, đang vướng gì. Tích hợp vào `main` ít nhất mỗi 2 ngày, không để cuối kỳ mới ghép.
