"""
Nhật ký KẾT QUẢ mỗi lượt — nguyên liệu thô để sau này rút ra kinh nghiệm.

Đây là việc 0 của `docs/learning_from_experience_spec.md`: trước khi cho trợ lý "học từ
kinh nghiệm", phải đo được đã. Không có mốc nền thì sau này không cách nào trả lời câu
hỏi duy nhất đáng hỏi — *nó có thật sự tốt lên không, hay chỉ khác đi?*

CHỈ ghi tín hiệu CỨNG — thứ quan sát được, không do model tự khai:

    xong           không có tool nào nổ, lượt kết thúc bình thường
    loi_tool       có tool nổ (hoặc model gọi tên tool không tồn tại)
    tu_choi        người dùng đáp "không" ở cổng duyệt
    bo_giua_chung  đang chờ duyệt thì người dùng nói sang chuyện khác
    het_vong       chạm `max_iterations` mà chưa xong
    hong           lượt ném ngoại lệ ra ngoài

CỐ Ý KHÔNG dùng thẻ `#emotion: happy` do chính model gắn, dù nó có sẵn: đó là model TỰ
CHẤM ĐIỂM MÌNH. Học từ nó sẽ dạy model cách *tuyên bố* thành công thay vì *đạt* thành
công — hỏng theo đúng kiểu khó phát hiện nhất, vì mọi số liệu đều đẹp.

LUẬT ƯU TIÊN: một lượt có tool nổ được tính `loi_tool` KỂ CẢ khi model gỡ lại được ở vòng
sau. Thứ đáng học là cú nổ đó, không phải việc cuối cùng vẫn trả lời được.

Mỗi bản ghi có CẢ `cau` (người dùng nói gì) lẫn `dap` (trợ lý đáp gì) — không phải để đọc
cho vui: ca thất bại khó thấy nhất là **yêu cầu một việc không tool nào làm được**. Lúc đó
model chỉ trả lời suông, `ket_qua` vẫn là `xong`, và nhìn từ tín hiệu cứng thì nó không
khác gì một lượt trò chuyện bình thường. Chỉ khi đọc `cau` + `dap` + phản ứng của người
dùng ở bản ghi KẾ TIẾP mới nhận ra được. Vì vậy mới có `phien`: chỉ được nối hai bản ghi
liền nhau khi chúng cùng một lần chạy.

Định dạng JSONL NỐI THÊM, không phải JSON ghi đè. Ghi nối không có bước đọc–sửa–ghi nên
không có cửa sổ cắt trắng file (`utils/atomic_json.py` nói vì sao điều đó quan trọng), và
đây cũng là dạng duy nhất còn đọc được khi file đang được ghi dở.

RIÊNG TƯ: file chứa nguyên văn câu người dùng nói. Chỉ nằm trên máy, đã gitignore, không
gửi đi đâu. `clear()` xoá sạch.
"""

import io
import json
import os
import uuid
from datetime import datetime

from utils.logger import get_logger

logger = get_logger(__name__)

KET_QUA = ("xong", "loi_tool", "tu_choi", "bo_giua_chung", "het_vong", "hong")

# Cắt câu người dùng cho khỏi phình file vì một lần đọc nhầm cả đoạn văn vào mic.
MAX_CAU = 300
# Câu trợ lý đáp dài hơn (đọc kết quả tìm kiếm, tóm tắt trang) nhưng vẫn phải có trần.
MAX_DAP = 600


class OutcomeLog:
    """Ghi nối JSONL, xoay vòng một bản. `path` rỗng = tắt hẳn (không ghi gì)."""

    def __init__(self, path=None, max_bytes=1_000_000):
        self.path = path or None
        self.max_bytes = int(max_bytes)
        # Định danh MỘT LẦN CHẠY. Bộ dò lỗ hổng năng lực đọc bản ghi kế bên để biết người
        # dùng phản ứng thế nào sau đó — nhưng chỉ được nối khi hai bản ghi CÙNG phiên.
        # Không có trường này thì lượt cuối hôm qua sẽ bị nối với lượt đầu hôm nay.
        # (Nhờ vậy khỏi phải lưu sẵn "câu lượt kế tiếp": thứ tự trong file đã mang tin đó.)
        self.phien = uuid.uuid4().hex[:8]

    def record(self, ban_ghi: dict):
        """Ghi một lượt. Hỏng ở đây KHÔNG được làm vỡ lượt nói chuyện — nuốt kèm log."""
        if not self.path:
            return
        try:
            dong = dict(ban_ghi)
            dong["khi"] = datetime.now().isoformat(timespec="seconds")
            dong["phien"] = self.phien
            dong["cau"] = (dong.get("cau") or "")[:MAX_CAU]
            dong["dap"] = (dong.get("dap") or "")[:MAX_DAP]
            self._xoay_neu_day()
            thu_muc = os.path.dirname(self.path)
            if thu_muc:
                os.makedirs(thu_muc, exist_ok=True)
            with io.open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(dong, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Không ghi được nhật ký kết quả: %s", e)

    def _xoay_neu_day(self):
        """Quá trần -> đẩy sang `.1` (đè bản `.1` cũ). Giữ ĐÚNG MỘT bản lưu.

        Một bản là đủ: cửa sổ phân tích của việc 0 là 30 ngày, mà trần 1 MB chứa được
        hàng chục nghìn lượt. Giữ nhiều bản chỉ tổ để dữ liệu riêng tư nằm lại lâu hơn
        mức cần.
        """
        try:
            if os.path.getsize(self.path) < self.max_bytes:
                return
        except OSError:
            return                      # chưa có file -> chưa cần xoay
        os.replace(self.path, self.path + ".1")

    def doc(self):
        """Mọi bản ghi đọc được, cũ trước mới sau. Dòng hỏng bị BỎ QUA, không ném.

        Bỏ qua dòng hỏng là có chủ đích: file có thể bị cắt giữa dòng cuối nếu máy tắt
        đúng lúc ghi, và một dòng cụt không được phép làm mù cả nhật ký.
        """
        ban_ghi = []
        for p in (self.path + ".1", self.path) if self.path else ():
            if not os.path.exists(p):
                continue
            try:
                with io.open(p, encoding="utf-8") as f:
                    for dong in f:
                        dong = dong.strip()
                        if not dong:
                            continue
                        try:
                            ban_ghi.append(json.loads(dong))
                        except ValueError:
                            continue
            except OSError as e:
                logger.warning("Không đọc được nhật ký kết quả '%s': %s", p, e)
        return ban_ghi

    def clear(self):
        """Xoá sạch nhật ký (cả bản lưu). Dữ liệu riêng tư -> phải có đường xoá."""
        if not self.path:
            return
        for p in (self.path, self.path + ".1"):
            try:
                os.remove(p)
            except OSError:
                pass
