"""
Sinh tests/TEST_INVENTORY.csv — bảng liệt kê test: ID, Tên, Mô tả, Trạng thái.

Trạng thái lấy từ một lần chạy pytest THẬT (nên chạy bằng môi trường có đủ phụ thuộc,
vd ml_env, để không bị 'Bỏ qua' oan các test cần numpy).

    python packaging/gen_test_inventory.py
"""

import csv
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "TEST_INVENTORY.csv")

STATUS_VI = {"PASSED": "Đạt", "SKIPPED": "Bỏ qua",
             "FAILED": "Lỗi", "ERROR": "Lỗi", "XFAIL": "Bỏ qua"}
LINE = re.compile(r"^(tests[\\/][\w./\\-]+\.py)::(\w+)\s+(PASSED|FAILED|SKIPPED|ERROR|XFAIL)")


def humanize(func):
    s = func[5:] if func.startswith("test_") else func
    return s.replace("_", " ").strip().capitalize()


def main():
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=no", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True)

    rows = []
    for line in proc.stdout.splitlines():
        m = LINE.match(line.strip())
        if m:
            path, func, status = m.groups()
            rows.append((f"{path.replace(os.sep, '/')}::{func}",
                         humanize(func), STATUS_VI.get(status, status)))

    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: Excel đọc đúng tiếng Việt
        w = csv.writer(f)
        w.writerow(["ID", "Tên", "Mô tả", "Trạng thái"])
        for i, (name, desc, status) in enumerate(rows, 1):
            w.writerow([f"T{i:03d}", name, desc, status])

    print(f"Đã ghi {len(rows)} test vào {OUT}")


if __name__ == "__main__":
    main()
