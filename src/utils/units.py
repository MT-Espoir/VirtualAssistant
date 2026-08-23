"""Định dạng đơn vị để ĐỌC bằng giọng nói (DRY: một nguồn duy nhất).

Trước đây có hai bản định dạng khoảng cách ở hai tầng (browser_protocol và
place_explain) — cùng một lỗi "cách 0 mét" phải sửa hai lần. Gom về đây.
"""


def format_km(value):
    """Số km -> chuỗi đọc được, hoặc None nếu không phải số.

    Làm tròn thô dần theo khoảng cách: người nghe không cần biết 1.353,4 km, và cũng
    không cần "0 mét" cho một chỗ cách 40 m.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    if v < 0.05:
        return "ngay gần đây"
    if v < 1:
        return f"{int(round(v * 1000 / 50.0) * 50)} mét"
    if v < 10:
        return f"{v:.1f} km".replace(".0 km", " km")
    if v < 100:
        return f"{int(round(v))} km"
    return f"{int(round(v / 10.0) * 10)} km"       # xa thì làm tròn thô cho dễ nghe


def say_distance(value):
    """Cụm từ hoàn chỉnh: "cách 350 mét" / "ngay gần đây". None nếu không biết.

    Tách khỏi `format_km` vì "cách ngay gần đây" đọc lên rất ngượng — chỗ nào cần cả
    giới từ thì dùng hàm này.
    """
    text = format_km(value)
    if not text:
        return None
    return f"cách {text}" if text[0].isdigit() else text
