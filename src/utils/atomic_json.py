"""
Ghi JSON theo kiểu THAY THẾ NGUYÊN TỬ — dùng chung cho mọi kho dữ liệu.

Vì sao cần: `open(path, "w")` **cắt trắng file trước** rồi mới ghi nội dung mới. Tiến
trình chết giữa hai bước đó — người dùng bấm Esc, tắt cửa sổ avatar, mất điện, Windows
kill — thì file còn lại rỗng hoặc cụt. Với `profile.json` (trí nhớ dài hạn tích luỹ qua
nhiều tháng) hay `habits.json` thì đó là mất vĩnh viễn: không có bản sao nào.

Cách chữa: ghi ra file tạm cùng thư mục, ép xuống đĩa, rồi ĐỔI TÊN đè lên. `os.replace`
là thao tác nguyên tử trên cả NTFS lẫn POSIX — người đọc hoặc thấy file cũ nguyên vẹn,
hoặc thấy file mới nguyên vẹn, không bao giờ thấy nửa chừng.

Đây là lý do một kho JSON phẳng vẫn đủ dùng ở quy mô này: thứ duy nhất một DB cho thêm mà
file phẳng không có chính là tính nguyên tử, và nó chỉ tốn chừng này code.
"""

import io
import json
import os


def write_json(path, data, indent=2):
    """Ghi `data` ra `path` dưới dạng JSON, thay thế nguyên tử. Tự tạo thư mục cha.

    Ném `OSError` y như `open` — nơi gọi giữ nguyên câu báo lỗi riêng của mình, vì mỗi
    kho cần nói rõ kho nào hỏng ("không lưu được sổ danh bạ" khác "không lưu được hồ sơ").

    KHÔNG chống được hai luồng cùng ghi MỘT kho: cả hai dùng chung một tên file tạm. Hiện
    không có kho nào bị ghi từ hai luồng (agent.run đã bị `_AGENT_LOCK` tuần tự hoá,
    scheduler có lock riêng), nên đổi lấy sự đơn giản: tên tạm cố định thì một lần chết
    giữa chừng để lại đúng MỘT file rác, và lần ghi sau đè lên luôn. Tên tạm sinh ngẫu
    nhiên sẽ rải rác file rác không ai dọn.
    """
    thu_muc = os.path.dirname(path)
    if thu_muc:
        os.makedirs(thu_muc, exist_ok=True)

    # File tạm phải CÙNG THƯ MỤC với đích: `os.replace` chỉ nguyên tử khi hai đường dẫn
    # nằm trên cùng một ổ đĩa, mà thư mục tạm của hệ thống thì không đảm bảo điều đó.
    tam = path + ".tmp"
    with io.open(tam, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
        # flush + fsync TRƯỚC khi đổi tên: thiếu bước này thì nội dung mới có thể còn nằm
        # trong bộ đệm OS lúc tên đã đúng -> mất điện vẫn mất nội dung, chỉ khác là bây
        # giờ mất cả bản cũ lẫn bản mới.
        f.flush()
        os.fsync(f.fileno())
    os.replace(tam, path)
