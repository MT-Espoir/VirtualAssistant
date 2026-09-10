"""
Cắt ảnh nhân vật gốc thành khung hình NỬA THÂN cho cửa sổ avatar.

Chạy:  python packaging/make_avatar_frames.py
Đọc:   src/ui/image/*_emotion.png   (ảnh gốc toàn thân, mỗi tấm một cỡ)
Ghi:   src/ui/image/frames/*.png    (khung hình hiển thị, mọi tấm CÙNG cỡ)

Chạy lại mỗi khi thêm hoặc sửa một ảnh gốc. Thêm `blinking_emotion.png` rồi chạy lại
là avatar tự biết chớp mắt (xem `ui/avatar_face.blink_frame`).

Ba việc script này làm, và lý do không việc nào bỏ được — số đo cụ thể ở
`docs/avatar_frames_spec.md`:

1. CANH THEO ĐỈNH ĐẦU, không theo khung bao alpha. Khung bao lệch nhau nhiều vì tay và
   tóc mỗi tư thế thò ra một kiểu; đỉnh đầu thì gần như trùng khít giữa các tấm. Canh
   sai thì nhân vật nhảy chỗ mỗi lần đổi cảm xúc.
2. THU NHỎ THEO ALPHA NHÂN TRƯỚC (premultiplied). Vùng trong suốt của ảnh gốc mang màu
   RGB đen, nên thu nhỏ thẳng sẽ trộn đen vào viền nhân vật -> viền xám bẩn.
3. ÉP ALPHA VỀ NHỊ PHÂN. Cửa sổ avatar đục nền bằng `-transparentcolor` của Windows,
   vốn không có alpha nửa vời: pixel viền mềm sẽ bị trộn với màu chìa khoá và hiện
   thành quầng hồng quanh nhân vật.
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src" / "ui" / "image"
OUT_DIR = SRC_DIR / "frames"

SUFFIX = "_emotion"

ALPHA_FLOOR = 30       # từ mức này coi là "có nét", dùng khi dò mốc canh ảnh
ALPHA_CUT = 110        # ngưỡng ép alpha về nhị phân (bản chạy: `ui/avatar.ALPHA_CUT`)
BLEED_PX = 12          # loang màu mép ra ngoài bấy nhiêu pixel, xem `_bleed`

# Mốc canh và khung cắt, tính theo CHIỀU CAO CANVAS của chính tấm ảnh gốc.
CROWN_ROW = 0.03       # hàng dùng để đo tâm đỉnh đầu, cách đỉnh đầu bấy nhiêu
MARGIN_TOP = 0.02      # chừa trên đỉnh đầu
CROP_H = 0.55          # chiều cao khung cắt: từ đỉnh đầu xuống ngang khuỷu tay
CROP_HALF_W = 0.30     # nửa chiều rộng khung cắt, tính từ tâm đỉnh đầu

# Khung hình bake ở 2x cỡ hiển thị gốc để phóng to hết cỡ vẫn còn nét (xem
# `ui/avatar.FRAME_OVERSAMPLE`). Chiều rộng làm tròn về số chẵn cho chia đôi được.
FRAME_H = 560
FRAME_W = 2 * round(FRAME_H * (2 * CROP_HALF_W) / CROP_H / 2)


def use_utf8_stdout():
    """Console Windows mặc định cp1252, không in nổi tiếng Việt -> script chết ở dòng
    print cuối cùng sau khi đã làm xong việc, trông như hỏng mà thật ra không."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def landmarks(image):
    """(hàng đỉnh đầu, cột tâm đỉnh đầu) của ảnh RGBA, tính bằng pixel.

    Hai mốc này gần như trùng khít giữa các tấm ảnh gốc, nên mọi thứ cắt ra từ chúng —
    khung hình avatar lẫn icon — đều canh theo đây. Xem `docs/avatar_frames_spec.md`.
    """
    alpha = np.asarray(image.getchannel("A"))
    height = alpha.shape[0]
    rows = np.flatnonzero((alpha > ALPHA_FLOOR).any(axis=1))
    if rows.size == 0:
        raise ValueError("ảnh trống, không có pixel nào đục")
    top = int(rows[0])

    row = min(height - 1, top + round(CROWN_ROW * height))
    cols = np.flatnonzero(alpha[row] > ALPHA_FLOOR)
    if cols.size == 0:
        raise ValueError("không đo được tâm đỉnh đầu")
    return top, (int(cols[0]) + int(cols[-1])) / 2.0


def resize_premultiplied(image, size):
    """Thu ảnh RGBA về `size`, nhân alpha vào RGB trước rồi chia ra sau. Alpha giữ NGUYÊN
    độ mềm — chỗ nào cần alpha nhị phân thì tự ép sau.

    Thu thẳng sẽ kéo màu của vùng trong suốt (đen) vào viền nhân vật; nhân trước thì
    vùng trong suốt góp trọng số 0 đúng như nó phải góp.
    """
    arr = np.asarray(image, dtype=np.float32)
    alpha = arr[..., 3:4] / 255.0
    premul = np.concatenate([arr[..., :3] * alpha, arr[..., 3:4]], axis=2)

    small = Image.fromarray(np.clip(premul, 0, 255).astype(np.uint8), "RGBA")
    small = np.asarray(small.resize(size, Image.LANCZOS), dtype=np.float32)

    out_alpha = small[..., 3:4]
    rgb = np.divide(small[..., :3] * 255.0, out_alpha,
                    out=np.zeros_like(small[..., :3]), where=out_alpha > 0)
    merged = np.concatenate([np.clip(rgb, 0, 255), out_alpha], axis=2)
    return Image.fromarray(merged.round().astype(np.uint8), "RGBA")


def _bleed(rgb, alpha, rounds=BLEED_PX):
    """Loang màu ở mép nhân vật ra vùng trong suốt quanh nó.

    Vùng trong suốt của khung hình mang màu gì thì lúc CHẠY, `ui/avatar.py` thu ảnh về
    cỡ cửa sổ sẽ trộn màu đó vào viền. Không loang thì viền bị kéo về đen. Alpha vẫn là
    nhị phân nên phần loang này không bao giờ hiện ra — nó chỉ tồn tại để phép thu ảnh
    có màu đúng mà lấy.
    """
    filled = rgb.copy()
    known = (alpha > 0).astype(np.float32)
    for _ in range(rounds):
        total = np.zeros_like(filled)
        count = np.zeros_like(known)
        for shift, axis in ((1, 0), (-1, 0), (1, 1), (-1, 1)):
            total += np.roll(filled * known[..., None], shift, axis=axis)
            count += np.roll(known, shift, axis=axis)
        grow = (known == 0) & (count > 0)
        filled[grow] = total[grow] / count[grow][..., None]
        known[grow] = 1.0
    return filled


def _bake(path):
    """Cắt + thu + ép alpha một ảnh gốc, trả ảnh khung hình đã xong."""
    image = Image.open(path).convert("RGBA")
    top, centre_x = landmarks(image)

    height = image.height
    crop_h = round(CROP_H * height)
    crop_w = round(crop_h * FRAME_W / FRAME_H)   # đúng tỉ lệ khung hình, không méo
    left = round(centre_x - crop_w / 2)
    upper = round(top - MARGIN_TOP * height)
    # Cắt lố ra ngoài canvas thì Pillow đệm bằng pixel trong suốt — đúng cái ta muốn.
    cropped = image.crop((left, upper, left + crop_w, upper + crop_h))

    small = np.asarray(resize_premultiplied(cropped, (FRAME_W, FRAME_H)), dtype=np.float32)
    hard = np.where(small[..., 3] >= ALPHA_CUT, 255.0, 0.0)
    rgb = _bleed(small[..., :3], hard)
    baked = np.concatenate([rgb, hard[..., None]], axis=2)
    return Image.fromarray(baked.round().astype(np.uint8), "RGBA")


def main():
    use_utf8_stdout()
    sources = sorted(SRC_DIR.glob("*%s.png" % SUFFIX))
    if not sources:
        print("Không thấy ảnh gốc nào (%s/*%s.png)" % (SRC_DIR, SUFFIX))
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sources:
        name = path.stem[:-len(SUFFIX)]
        try:
            frame = _bake(path)
        except (OSError, ValueError) as e:
            print("BỎ QUA %-22s %s" % (path.name, e))
            continue
        out = OUT_DIR / ("%s.png" % name)
        frame.save(out, optimize=True)
        print("%-22s -> %-24s %dx%d  %d KB"
              % (path.name, out.name, frame.width, frame.height,
                 out.stat().st_size // 1024))
    print("\nXong. Khung hình ở: %s" % OUT_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
