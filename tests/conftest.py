"""Cấu hình pytest: thêm thư mục src vào sys.path để import core/, nlp/, ..."""

import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
