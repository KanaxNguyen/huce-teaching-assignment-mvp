# Bàn giao MVP HUCE TKB

## Phạm vi phiên bản đầu

MVP bao phủ trọn luồng nghiệp vụ của một người phụ trách bộ môn:

1. Tải lịch học, nguyện vọng giảng viên và bảng mẫu cũ.
2. Chuẩn hóa lớp, giảng viên, lịch học và nhóm lớp ghép.
3. Xem, thêm, chỉnh sửa, bật/tắt hoặc xóa ràng buộc.
4. Điều chỉnh độ cứng và trọng số của seminar.
5. Chạy tối ưu, giữ phân công đã khóa và xác nhận nhóm ghép.
6. Kiểm tra kết quả, lịch tuần và xung đột dữ liệu.
7. Cấu hình học kỳ, năm học, khoảng ngày và Calendar.
8. Xuất Excel, ICS, CSV và JSON để bàn giao hoặc tích hợp.

## Tiêu chí chấp nhận

- Nhận đủ 175 lớp học phần từ bộ dữ liệu ngày 28/07/2026.
- Nhận diện 41 cặp lớp ghép có lịch trùng và cùng phòng.
- Giữ Giải tích 1 – 71CSQT cho Nguyễn Bằng Giang.
- Giữ Đại số tuyến tính – 71CSQT cho Phạm Đức Thoan.
- Nguyện vọng và seminar là ràng buộc mềm mặc định trọng số 0,8.
- Không để giảng viên dạy hai lớp đơn trùng lịch.
- Workbook xuất có 7 sheet kiểm tra và không có xung đột cứng.
- API xuất Excel, ICS, CSV và JSON hoạt động sau mỗi lần tối ưu thành công.
- ICS dùng múi giờ `Asia/Ho_Chi_Minh`, UID ổn định, gộp lớp ghép và lọc riêng từng giảng viên.

## Vai trò và giới hạn MVP

Phiên bản này dành cho một nhóm vận hành nội bộ, chưa có đăng nhập nhiều người dùng hoặc phân quyền. Dữ liệu được lưu bằng SQLite và tệp cục bộ/ổ đĩa bền vững của dịch vụ. Khi triển khai cho nhiều khoa hoặc nhiều người sửa đồng thời, cần nâng cấp database, xác thực và nhật ký thay đổi.

## Sao lưu

Cần sao lưu định kỳ thư mục `storage`, đặc biệt là `storage/database` và `storage/exports`. Không đưa workbook thật hoặc database lên GitHub.
