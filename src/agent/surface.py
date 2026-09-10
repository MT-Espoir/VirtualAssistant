"""
Bề mặt tool — trả lời ĐÚNG MỘT câu hỏi: lượt này model được thấy prompt gì và tool nào.

Hợp đồng (duck-typing, không abstract class — cả codebase dùng lối này):

    select(user_text, registry) -> (system_prompt, tool_specs)

Vì sao tách ra thành một khái niệm riêng: chi phí input mỗi lượt tỉ lệ TUYẾN TÍNH với số
tool gửi đi. Ở 47 tool, gửi hết là chấp nhận được (19.257 ký tự ≈ 6.450 token). Ở 100–200
tool thì không, và cách chữa là đổi CÁCH CHIẾU tool vào prompt:

    all      O(N)   — gửi hết (lớp này)
    indexed  O(√N)  — mục lục nhóm + meta-tool mở nhóm theo yêu cầu
    code     O(1)   — một tool chạy code, tool thành hàm đọc theo yêu cầu

Ba thứ đó KHÔNG phải ba kiến trúc mà là ba cài đặt của cùng hợp đồng trên. Agent chỉ biết
hợp đồng, nên lên bậc = thêm một lớp ở đây + đổi config, KHÔNG sửa vòng lặp agent và không
sửa một định nghĩa tool nào. Xem `docs/tool_surface_spec.md`.

`agent/router.py::Router` là cài đặt thứ hai của cùng hợp đồng (thu hẹp theo case bằng một
lượt LLM phân loại) — nó không phải một khái niệm song song.
"""


class AllTools:
    """Gửi TOÀN BỘ tool + một prompt cố định. Hành vi mặc định khi không có router.

    Đúng lựa chọn ở quy mô hiện tại: provider mạnh chọn đúng tool giữa cả 47 tool mà không
    cần thu hẹp, và bỏ được lượt LLM phân loại (đo được: 2,86 -> 1,86 call/lượt).
    """

    def __init__(self, system: str):
        self.system = system

    def select(self, user_text, registry):
        # `user_text` không dùng tới — bề mặt này không phụ thuộc câu người dùng nói. Vẫn
        # nhận nó để đúng hợp đồng: các bề mặt khác (router, indexed) đều cần.
        return self.system, registry.specs()
