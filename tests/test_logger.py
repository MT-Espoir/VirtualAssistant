"""
Ghi log ra file có xoay vòng.

Hai tính chất phải giữ:
  1. File log KHÔNG phình vô hạn (xoay vòng có trần) và SỐNG QUA nhiều lần chạy — khác
     `assistant.log`, vốn bị `launch_assistant.vbs` ghi đè mỗi lần mở.
  2. Log hỏng KHÔNG được làm chết trợ lý: không mở được file thì chạy tiếp bằng console.

Không test `_configure_root` trực tiếp: nó cấu hình root logger toàn tiến trình một lần,
đụng vào là làm nhiễu mọi test khác. Phần quyết định đã tách ra thành `_nen_ghi_file` và
`_file_handler` để test được mà không chạm trạng thái toàn cục.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

try:
    import pytest
except ImportError:
    pytest = None

from utils import logger as logger_mod


# --------------------------- có ghi file hay không --------------------------- #

def test_khong_ghi_file_khi_dang_chay_pytest():
    """Log của test trộn vào log ứng dụng chỉ làm nhiễu lúc chẩn đoán."""
    assert "pytest" in sys.modules            # tiền đề của test này
    assert logger_mod._nen_ghi_file() is False


def test_co_ghi_file_khi_chay_that(monkeypatch, tmp_path):
    """Ngoài pytest + có LOG_FILE -> ghi. Giả lập bằng cách gỡ pytest khỏi sys.modules."""
    monkeypatch.setattr(logger_mod.config, "LOG_FILE", str(tmp_path / "app.log"))
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    assert logger_mod._nen_ghi_file() is True


def test_LOG_FILE_rong_thi_tat_han(monkeypatch):
    monkeypatch.setattr(logger_mod.config, "LOG_FILE", "")
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    assert logger_mod._nen_ghi_file() is False


# --------------------------- handler xoay vòng --------------------------- #

def test_handler_xoay_vong_dung_tran_da_cau_hinh(monkeypatch, tmp_path):
    duong_dan = tmp_path / "app.log"
    monkeypatch.setattr(logger_mod.config, "LOG_FILE", str(duong_dan))
    monkeypatch.setattr(logger_mod.config, "LOG_MAX_BYTES", 1234)
    monkeypatch.setattr(logger_mod.config, "LOG_BACKUP_COUNT", 5)

    h = logger_mod._file_handler()
    try:
        assert isinstance(h, RotatingFileHandler)
        assert h.maxBytes == 1234 and h.backupCount == 5
    finally:
        h.close()


def test_tu_tao_thu_muc_cha(monkeypatch, tmp_path):
    """LOG_FILE trỏ vào thư mục chưa có (mặc định `logs/app.log`) -> tự tạo, không nổ."""
    duong_dan = tmp_path / "chua" / "co" / "app.log"
    monkeypatch.setattr(logger_mod.config, "LOG_FILE", str(duong_dan))
    h = logger_mod._file_handler()
    try:
        assert duong_dan.parent.is_dir()
    finally:
        h.close()


def test_file_ghi_kem_NGAY_khong_chi_gio(monkeypatch, tmp_path):
    """File sống qua nhiều ngày -> mốc chỉ có giờ là mốc mơ hồ.

    (Console vẫn chỉ hiện giờ — người đang ngồi xem biết hôm nay là ngày nào.)
    """
    duong_dan = tmp_path / "app.log"
    monkeypatch.setattr(logger_mod.config, "LOG_FILE", str(duong_dan))
    h = logger_mod._file_handler()
    try:
        h.emit(logging.LogRecord("t", logging.INFO, __file__, 1, "xin chào", None, None))
    finally:
        h.close()
    dong = duong_dan.read_text(encoding="utf-8")
    assert "xin chào" in dong
    assert dong[:4].isdigit()                 # bắt đầu bằng năm, vd "2026-08-28 21:26:22"


def test_khong_mo_duoc_file_thi_tra_None_chu_khong_nem(monkeypatch, tmp_path):
    """Trợ lý phải khởi động được kể cả khi đường dẫn log hỏng."""
    ke_chan = tmp_path / "la_mot_file"
    ke_chan.write_text("x", encoding="utf-8")
    # Lấy một FILE làm thư mục cha -> mkdir chắc chắn hỏng.
    monkeypatch.setattr(logger_mod.config, "LOG_FILE", str(ke_chan / "app.log"))
    assert logger_mod._file_handler() is None


# --------------------------- mặc định --------------------------- #

def test_mac_dinh_khong_trung_assistant_log():
    """Logger và redirect của .vbs KHÔNG được cùng mở một file — chèn lẫn nhau.

    `assistant.log` do `launch_assistant.vbs` ghi bằng `>`; LOG_FILE phải là chỗ khác.
    """
    from utils.config import config
    assert config.LOG_FILE
    assert os.path.basename(config.LOG_FILE) != "assistant.log"
    assert os.path.isabs(config.LOG_FILE)     # quy về gốc dự án, không theo cwd
