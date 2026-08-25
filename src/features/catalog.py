"""
Danh mục feature của trợ lý — nguồn duy nhất trả lời "trợ lý này có những gì".

`FEATURES` là DANH SÁCH TƯỜNG MINH, cố ý không dò thư mục tự động. Hai lý do:

1. Hiệu suất. Thứ tự nạp quyết định thứ tự tool specs trong prompt, mà Ollama tái dùng
   KV cache theo tiền tố — thứ tự đổi giữa hai lần chạy là mất ~16-20s mỗi lượt
   (`docs/latency_optimization_spec.md`). Đo được: đổi chỗ ĐÚNG HAI tool kề nhau làm
   tiền tố chung rơi từ 19.351 xuống 807 ký tự. `os.listdir()` không hứa thứ tự ổn định.
2. Đọc được. Muốn biết trợ lý có những gì thì đọc đúng một danh sách, không phải suy ra
   từ cây thư mục.

Tách khỏi `features/__init__.py` để `from features.contract import ...` không kéo theo
toàn bộ feature (và mọi thứ chúng import) chỉ vì cần một dataclass.

Thêm feature = tạo package dưới `features/` rồi thêm một dòng vào đây.
Gỡ feature  = xoá dòng đó, hoặc để `enabled` trả False.
"""

from features.places.feature import FEATURE as PLACE

# THỨ TỰ CÓ Ý NGHĨA — xem lý do 1 ở trên.
#
# Trong lúc migrate, các feature CHƯA chuyển vẫn nằm ở `agent/tools.py::build_default_registry`
# và được đăng ký TRƯỚC danh sách này. `place` vốn là khối đăng ký CUỐI CÙNG trong hàm đó,
# nên rút nó ra trước rồi nạp lại ở đây cho ra đúng thứ tự tool như cũ — ảnh chụp
# `tests/fixtures/tool_specs_baseline.json` không đổi một byte.
#
# Suy ra quy tắc cho các bước sau: MIGRATE NGƯỢC THỨ TỰ ĐĂNG KÝ (contacts -> routines ->
# tasks -> profile -> screen -> web -> browser -> schedule -> nhóm lõi), mỗi lần rút khối
# cuối cùng còn lại và thêm vào ĐẦU danh sách này. Làm vậy thì tiền tố prompt không xê
# dịch một lần nào trong suốt đợt refactor.
FEATURES = [
    PLACE,
]
