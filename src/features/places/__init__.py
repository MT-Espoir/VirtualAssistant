"""
Feature `place` — tra cứu địa điểm.

Feature ĐẦU TIÊN chuyển sang hợp đồng ở `features/contract.py`, chọn làm pilot vì nó
rải rộng nhất: 7 file logic, 6 tool, một đoạn prompt riêng, một panel, cộng phần dựng
service trong `app.py`. Gom hết về đây thì thêm/sửa tính năng địa điểm chỉ đụng một
thư mục.

Bố cục:
    service.py       PlacesService — nguồn dữ liệu, lọc, chính sách
    deep_research.py tra sâu qua nhiều nguồn (Lane 3); đặt tên này để khỏi lẫn với
                     package `research/` dùng chung ở top-level
    ranking.py       xếp hạng ứng viên
    attributes.py    trích thuộc tính (giờ đóng cửa, tiện ích) — không đặt tên
                     `features.py` vì nằm sẵn trong package `features/`
    identity.py      gộp trùng, nhận diện thương hiệu
    refine.py        tinh chỉnh kết quả ở lượt sau ("chỗ nào mở muộn hơn")
    explain.py       diễn giải vì sao chọn chỗ đó
    tools.py         đăng ký 6 tool
    prompt.py        đoạn prompt riêng (router case "place")
    feature.py       khai báo Feature

Package này CỐ Ý không import gì ở cấp module. `llm/prompt_texts.py` chỉ cần
`features.places.prompt`, mà nhập một submodule thì Python chạy `__init__.py` trước —
để `tools` ở đây thì chỉ muốn đoạn prompt cũng kéo theo cả tầng đăng ký tool, và mở
đường cho import vòng. Khai báo Feature vì vậy nằm ở `feature.py`.
"""
