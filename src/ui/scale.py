"""Trạng thái tỷ lệ liên tục dùng chung cho các bề mặt UI.

Nguồn điều khiển (giọng nói, bàn phím, camera/gesture trong tương lai) chỉ cần gửi
``scale`` tuyệt đối hoặc ``scale_delta`` tương đối. Controller không biết nguồn đó là
gì, nên HUD không phải thay đổi khi bổ sung nhận diện cử chỉ.
"""

import math


class ContinuousScale:
    """Giữ một hệ số tỷ lệ thực, có biên nhưng không có các nấc cố định."""

    def __init__(self, value=1.0, minimum=0.65, maximum=1.80):
        if minimum <= 0 or maximum < minimum:
            raise ValueError("Khoảng tỷ lệ không hợp lệ")
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.value = self.minimum
        self.set(value)

    def set(self, value):
        """Đặt tỷ lệ tuyệt đối; giá trị lỗi/không hữu hạn được bỏ qua an toàn."""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return self.value
        if not math.isfinite(number):
            return self.value
        self.value = max(self.minimum, min(self.maximum, number))
        return self.value

    def adjust(self, delta):
        """Cộng một lượng bất kỳ, phù hợp cả bước giọng nói lẫn delta nhỏ từ gesture."""
        try:
            number = float(delta)
        except (TypeError, ValueError):
            return self.value
        if not math.isfinite(number):
            return self.value
        return self.set(self.value + number)
