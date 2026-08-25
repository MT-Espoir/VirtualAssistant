"""
Kiến trúc feature-module của trợ lý.

    contract.py   hợp đồng `Feature` + bộ nạp `load_features`
    catalog.py    danh sách `FEATURES` — nạp gì, theo thứ tự nào
    <tên>/        một feature: service, tool, prompt, panel gom về một chỗ

Package này CỐ Ý để trống. Danh mục nằm ở `catalog.py` chứ không ở đây, để
`from features.contract import Feature` không kéo theo toàn bộ feature (và mọi thứ
chúng import) chỉ vì cần một dataclass.

Xem `docs/module_refactor_sprint.md`.
"""
