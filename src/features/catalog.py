"""
Danh mục feature của trợ lý — nguồn duy nhất trả lời "trợ lý này có những gì".

`FEATURES` là DANH SÁCH TƯỜNG MINH, cố ý không dò thư mục tự động. Hai lý do:

1. Hiệu suất. Thứ tự nạp quyết định thứ tự tool specs trong prompt, mà Ollama tái dùng
   KV cache theo tiền tố — thứ tự đổi giữa hai lần chạy là mất ~16-20s mỗi lượt
   (`docs/latency_optimization_spec.md`). Đo được: đổi chỗ ĐÚNG HAI tool kề nhau làm
   tiền tố chung rơi từ 19.351 xuống 807 ký tự. `os.listdir()` không hứa thứ tự ổn định.
2. Đọc được. Muốn biết trợ lý có những gì thì đọc đúng một danh sách, không phải suy ra
   từ cây thư mục.

Tách khỏi `features/__init__.py` để việc nhập hợp đồng không kéo theo toàn bộ feature
(và mọi thứ chúng import) chỉ vì cần một dataclass.

Thêm feature = tạo package dưới `features/` rồi thêm một dòng vào đây.
Gỡ feature  = xoá dòng đó, hoặc để `enabled` trả False.
"""

from features.browser.feature import FEATURE as BROWSER
from features.pim.feature import FEATURE as PIM
from features.places.feature import FEATURE as PLACE
from features.profile.feature import FEATURE as PROFILE
from features.schedule.feature import FEATURE as SCHEDULE
from features.screen.feature import FEATURE as SCREEN
from features.system.feature import FEATURE as SYSTEM
from features.task.feature import FEATURE as TASK
from features.weather.feature import FEATURE as WEATHER
from features.web.feature import FEATURE as WEB

# THỨ TỰ CÓ Ý NGHĨA — xem lý do 1 ở trên. Đây giờ là NGUỒN DUY NHẤT quyết định thứ tự
# tool trong prompt; đổi thứ tự các dòng dưới đây là làm nguội KV cache của mọi người dùng.
#
# Đợt migrate giữ nguyên thứ tự cũ bằng cách rút khối đăng ký CUỐI CÙNG trước (place ->
# pim -> task -> profile -> screen -> web_search -> browser -> schedule). Riêng bước cuối
# — nhóm lõi — BUỘC phải đổi thứ tự: system/web/weather cài răng lược trong một khối
# `reg.register` liên tiếp (system x7, web x2, weather x1, web x4), tách theo case thì
# không cách nào giữ nguyên. Đây là lần đổi DUY NHẤT và CÓ CHỦ ĐÍCH của cả đợt; ảnh chụp
# `tests/fixtures/tool_specs_baseline.json` đã chụp lại tại commit đó.
FEATURES = [
    SYSTEM,
    WEB,
    WEATHER,
    SCHEDULE,
    BROWSER,
    SCREEN,
    PROFILE,
    TASK,
    PIM,
    PLACE,
]
