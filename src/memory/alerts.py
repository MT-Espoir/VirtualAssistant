"""
Soi nhật ký kết quả tìm DẤU HIỆU BỊ TẤN CÔNG.

Vì sao cần, dù đã vá xong sáu đợt: mọi lớp phòng ngừa đều nâng chi phí tấn công chứ không
triệt tiêu nó. Hệ này chắc chắn sẽ bị chọc thủng lúc nào đó — và **không biết mình đã bị
chọc thì mất luôn cơ hội phản ứng**. Trước file này, khả năng phát hiện của hệ bằng 0.

Chạy:
    cd src && python -m memory.alerts            # soi toàn bộ nhật ký
    cd src && python -m memory.alerts 7          # chỉ 7 ngày gần đây

NGUYÊN TẮC THIẾT KẾ: chỉ dùng thứ nhật ký THẬT SỰ có (`cau`, `dap`, `tool`, `ket_qua`,
`nguon_ngoai`, `phien`). Không đòi ghi thêm trường chỉ để cảnh báo đẹp hơn — mỗi trường
thêm vào là thêm dữ liệu riêng tư nằm trên đĩa, mà đó chính là thứ ta đang bảo vệ.

Hàm THUẦN, không I/O — nơi gọi đưa bản ghi vào. Nhờ vậy test được mà không cần nhật ký thật.
"""

CAO, VUA = "cao", "vừa"


# Bao nhiêu lượt sau một lượt đọc nội dung ngoài thì ngữ cảnh vẫn còn coi là nhiễm.
# Khớp với `Agent._nhiem` (cửa sổ STM), nhưng ở đây phải DỰNG LẠI từ nhật ký vì bản ghi
# chỉ có cờ `nguon_ngoai` của CHÍNH lượt đó, không có trạng thái nhiễm mang sang.
CUA_SO_NHIEM = 11


def _tool_ngoai_dung_truoc(ban_ghi, chi_so, tool_ngoai):
    """Trước tool thứ `chi_so` trong CÙNG lượt, có tool nào trả nội dung ngoài chưa?

    THỨ TỰ là tất cả. `web_search_list` vừa trả nội dung ngoài vừa đẩy truy vấn ra ngoài,
    nên một lần tìm kiếm BÌNH THƯỜNG cũng làm bản ghi mang cả hai cờ. Không xét thứ tự thì
    luật kêu ở mọi lượt tìm kiếm — đúng kiểu cảnh báo thành tiếng ồn rồi không ai đọc nữa.
    (Phát hiện khi chạy thật trên nhật ký đầu tiên: 5/5 cảnh báo đều là dương tính giả.)
    """
    return any(t in tool_ngoai for t in (ban_ghi.get("tool") or [])[:chi_so])


def soi_mot_luot(ban_ghi, tool_ro_ri, tool_ben_vung, tool_ngoai=(), nhiem_tu_truoc=False):
    """Một bản ghi -> danh sách cảnh báo. [] nếu không có gì đáng ngờ.

    `nhiem_tu_truoc`: một lượt TRƯỚC đó trong cùng phiên đã chạm nội dung ngoài.
    """
    canh_bao = []
    ket_qua = ban_ghi.get("ket_qua")
    da_chay = ket_qua == "xong"
    duoi = " — VÀ ĐÃ CHẠY" if da_chay else " (cổng đã chặn)"
    muc = CAO if da_chay else VUA

    for i, ten in enumerate(ban_ghi.get("tool") or []):
        sau_noi_dung_ngoai = nhiem_tu_truoc or _tool_ngoai_dung_truoc(ban_ghi, i, tool_ngoai)
        if not sau_noi_dung_ngoai:
            continue
        if ten in tool_ro_ri:
            canh_bao.append(_dung(ban_ghi, "ro_ri_sau_noi_dung_ngoai", muc, ten,
                                  "gửi dữ liệu RA NGOÀI sau khi đã đọc nội dung ngoài" + duoi))
        elif ten in tool_ben_vung:
            canh_bao.append(_dung(ban_ghi, "ghi_tri_nho_sau_noi_dung_ngoai", muc, ten,
                                  "ghi thứ sẽ QUAY LẠI prompt, sau khi đã đọc nội dung ngoài" + duoi))

    # Routine là các bước sẽ TỰ THỰC THI về sau. Người dùng không hề nhắc tới routine mà
    # trợ lý lại đi tạo một cái, thì hoặc model hiểu sai, hoặc có ai đó bảo nó làm vậy.
    if "create_routine" in (ban_ghi.get("tool") or []):
        cau = (ban_ghi.get("cau") or "").lower()
        if not any(k in cau for k in ("routine", "quy trình", "quy trinh")):
            canh_bao.append(_dung(ban_ghi, "tao_routine_khong_ai_yeu_cau", CAO,
                                  "create_routine",
                                  "tạo quy trình tự chạy mà câu người dùng không hề nhắc tới"))
    return canh_bao


def _dung(ban_ghi, luat, muc, tool, vi_sao):
    return {"muc": muc, "luat": luat, "tool": tool, "vi_sao": vi_sao,
            "khi": ban_ghi.get("khi"), "phien": ban_ghi.get("phien"),
            "cau": ban_ghi.get("cau")}


def soi(ban_ghi_list, tool_ro_ri, tool_ben_vung, tool_ngoai=()):
    """Nhiều bản ghi -> mọi cảnh báo, mức CAO lên trước.

    Vết nhiễm được DỰNG LẠI theo phiên: bản ghi chỉ nói lượt đó có chạm nội dung ngoài
    hay không, không nói trạng thái nhiễm mang sang từ lượt trước — mà đó mới là thứ cổng
    dùng lúc chạy.
    """
    ra = []
    con_lai = {}                       # phiên -> còn bao nhiêu lượt nữa vẫn coi là nhiễm
    for r in ban_ghi_list or []:
        phien = r.get("phien")
        nhiem_tu_truoc = con_lai.get(phien, 0) > 0
        ra.extend(soi_mot_luot(r, tool_ro_ri, tool_ben_vung, tool_ngoai, nhiem_tu_truoc))
        if r.get("nguon_ngoai"):
            con_lai[phien] = CUA_SO_NHIEM
        elif nhiem_tu_truoc:
            con_lai[phien] -= 1
    ra.sort(key=lambda c: 0 if c["muc"] == CAO else 1)
    return ra


def ke_canh_bao(canh_bao):
    """Cảnh báo -> chuỗi cho người đọc. '' nếu sạch."""
    if not canh_bao:
        return "Không thấy dấu hiệu đáng ngờ nào."
    dong = [f"Thấy {len(canh_bao)} dấu hiệu đáng ngờ:"]
    for c in canh_bao:
        dong.append(f"  [{c['muc'].upper()}] {c['khi']} · {c['tool']} — {c['vi_sao']}")
        dong.append(f"          câu: {(c['cau'] or '')[:80]}")
    return "\n".join(dong)


def _main(argv):
    """Soi nhật ký thật. Lấy nhóm tool `exfil`/`persistent` từ CHÍNH registry đang chạy —
    không chép tay danh sách, vì bảng chép tay sẽ lệch ngay lần thêm tool sau."""
    import dataclasses
    from unittest.mock import MagicMock

    from agent.tools import ToolRegistry
    from features.catalog import FEATURES
    from features.contract import FeatureContext, load_features
    from memory.outcomes import OutcomeLog
    from utils.config import config

    ctx = {f.name: MagicMock() for f in dataclasses.fields(FeatureContext)}
    ctx["mcp"] = None
    reg = ToolRegistry()
    load_features(reg, FeatureContext(**ctx), FEATURES)
    ro_ri = {n for n in reg.names() if reg.get(n).exfil}
    ben_vung = {n for n in reg.names() if reg.get(n).persistent}

    ban_ghi = OutcomeLog(config.OUTCOMES_FILE).doc()
    if argv:
        try:                       # lọc theo số NGÀY gần đây
            from datetime import datetime, timedelta
            moc = (datetime.now() - timedelta(days=int(argv[0]))).isoformat()
            ban_ghi = [r for r in ban_ghi if (r.get("khi") or "") >= moc]
        except ValueError:
            pass
    print(f"Đã đọc {len(ban_ghi)} lượt từ {config.OUTCOMES_FILE}")
    ngoai = {n for n in reg.names() if reg.get(n).untrusted_output}
    print(ke_canh_bao(soi(ban_ghi, ro_ri, ben_vung, ngoai)))


if __name__ == "__main__":
    import sys
    _main(sys.argv[1:])
