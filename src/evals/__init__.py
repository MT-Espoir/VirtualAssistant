"""Bộ khung đánh giá (eval) độ tin cậy của agent.

Đo hai thứ QUAN TRỌNG mà unit test không bắt được: (1) model có gọi ĐÚNG tool cho
mỗi yêu cầu không, (2) router phân loại đúng case không. Chạy qua LLM THẬT (theo
config) nhưng tool KHÔNG thực thi (RecordingRegistry chỉ ghi lại tên tool) -> đo
được hành vi chọn tool mà không gây tác dụng phụ (không mở app, không đổi âm lượng...).

Chạy:  cd src && python -m evals.run_eval
"""
