"""
Tạo icon 'assistant.ico' (khuôn mặt robot kiểu EVE, khớp avatar) bằng Pillow.

Chạy:  python packaging/make_icon.py
Kết quả: assistant.ico + assistant.png ở thư mục gốc dự án.
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Màu khớp ui/avatar.py
BLUE = (76, 201, 240, 255)
BEZEL = (245, 245, 245, 255)
RING = (74, 74, 74, 255)
SCREEN = (10, 10, 12, 255)

S = 256


def draw_face():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Khung bezel trắng -> vòng xám -> màn hình đen (bo góc, giống thiết bị)
    d.rounded_rectangle((10, 10, 246, 246), radius=52, fill=BEZEL)
    d.rounded_rectangle((22, 22, 234, 234), radius=44, fill=RING)
    d.rounded_rectangle((34, 34, 222, 222), radius=34, fill=SCREEN)

    # Mắt: 2 khối vuông bo góc xanh dương (pose neutral)
    ey = 110
    for cx in (100, 156):
        d.rounded_rectangle((cx - 20, ey - 22, cx + 20, ey + 22), radius=8, fill=BLUE)

    # Miệng: cười (cung dưới, mở lên)
    d.arc((92, 138, 164, 200), start=20, end=160, fill=BLUE, width=12)

    return img


def main():
    img = draw_face()
    png_path = os.path.join(ROOT, "assistant.png")
    ico_path = os.path.join(ROOT, "assistant.ico")
    img.save(png_path)
    img.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                              (64, 64), (128, 128), (256, 256)])
    print("Đã tạo:", ico_path)
    print("Đã tạo:", png_path)


if __name__ == "__main__":
    main()
