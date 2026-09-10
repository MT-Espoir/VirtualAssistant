"""
Tạo icon 'assistant.ico' bằng cách cắt KHUÔN MẶT nhân vật từ chính ảnh avatar.

Chạy:  python packaging/make_icon.py
Đọc:   src/ui/image/default_emotion.png   (ảnh gốc, cùng tấm avatar dùng lúc rảnh)
Kết quả: assistant.ico + assistant.png ở thư mục gốc dự án.

Cắt từ ảnh GỐC chứ không phải từ khung hình đã bake (`src/ui/image/frames/`): khung hình
bake bị ép alpha nhị phân cho hợp `-transparentcolor` của Windows, còn .ico thì đọc được
alpha thật, nên lấy thẳng ảnh gốc sẽ có mép mượt hơn.

Mốc canh và phép thu ảnh dùng lại `make_avatar_frames` — icon và avatar phải cắt theo
cùng một cách, nếu không mỗi lần đổi ảnh nhân vật lại phải chỉnh hai chỗ.
"""

import os
import sys

from PIL import Image

from make_avatar_frames import landmarks, resize_premultiplied, use_utf8_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "ui", "image", "default_emotion.png")

# Ô vuông quanh đầu, tính theo CHIỀU CAO CANVAS ảnh gốc, neo ở (tâm đỉnh đầu, đỉnh đầu).
# 0.28 là mức ôm trọn tóc mà mặt vẫn đủ to: hẹp hơn thì cụt tóc hai bên và mất dáng đầu,
# rộng hơn thì ở cỡ 16px chỉ còn thấy một mảng trắng.
HEAD_SIDE = 0.28
HEAD_TOP = 0.02

S = 256
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def head_icon(path):
    """Cắt ô vuông quanh đầu rồi thu về S x S, giữ nền trong suốt."""
    image = Image.open(path).convert("RGBA")
    top, centre_x = landmarks(image)

    side = round(HEAD_SIDE * image.height)
    left = round(centre_x - side / 2)
    upper = round(top - HEAD_TOP * image.height)
    # Cắt lố ra ngoài canvas thì Pillow đệm bằng pixel trong suốt — đúng cái ta muốn.
    cropped = image.crop((left, upper, left + side, upper + side))
    return resize_premultiplied(cropped, (S, S))


def main():
    use_utf8_stdout()
    if not os.path.exists(SRC):
        print("Không thấy ảnh gốc:", SRC)
        return 1

    img = head_icon(SRC)
    png_path = os.path.join(ROOT, "assistant.png")
    ico_path = os.path.join(ROOT, "assistant.ico")
    img.save(png_path)
    img.save(ico_path, sizes=ICO_SIZES)
    print("Đã tạo:", ico_path)
    print("Đã tạo:", png_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
