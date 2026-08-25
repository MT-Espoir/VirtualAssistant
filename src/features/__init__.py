"""
Danh mục feature của trợ lý.

`FEATURES` là DANH SÁCH TƯỜNG MINH, cố ý không dò thư mục tự động. Hai lý do:

1. Hiệu suất. Thứ tự nạp quyết định thứ tự tool specs trong prompt, mà Ollama tái dùng
   KV cache theo tiền tố — thứ tự đổi giữa hai lần chạy là mất ~16-20s mỗi lượt
   (`docs/latency_optimization_spec.md`). `os.listdir()` không hứa thứ tự ổn định.
2. Đọc được. Muốn biết trợ lý có những gì thì đọc đúng một danh sách, không phải suy
   ra từ cây thư mục.

Thêm feature = tạo package dưới `features/` rồi thêm một dòng vào đây.
Gỡ feature = xoá dòng đó (hoặc để `enabled` trả False).
"""

from features.contract import (Feature, FeatureContext, LoadedFeature, LoadReport,
                               SPEC_CHARS_BUDGET, load_features)

# Thứ tự có ý nghĩa — xem lý do 1 ở trên. Thêm vào CUỐI để không xáo tiền tố sẵn có.
FEATURES = []

__all__ = ["Feature", "FeatureContext", "LoadedFeature", "LoadReport",
           "SPEC_CHARS_BUDGET", "load_features", "FEATURES"]
