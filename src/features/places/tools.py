"""
Tool tra địa điểm — phần đăng ký của feature `places`.

Chuyển nguyên khối từ `agent/tools.py::_register_place_tools` (2026-08-25), thân hàm
KHÔNG sửa một dòng nào; chỉ đổi chữ ký sang `register(reg, ctx)` của hợp đồng feature
và lấy dependency từ ctx. Ảnh chụp `tests/fixtures/tool_specs_baseline.json` chứng minh
specs không đổi một byte.
"""

from datetime import datetime

from agent.tools import Tool
from utils.config import config
from utils.logger import get_logger

logger = get_logger(__name__)


def register(reg, ctx):
    """Tra ĐỊA ĐIỂM — hai ý định tách đôi.

    `find_nearby` : theo LOẠI, quanh một điểm  -> ràng buộc KHOẢNG CÁCH
    `find_place`  : ĐÚNG MỘT CHỖ có tên        -> ràng buộc TÊN (và khu vực nếu người nói)

    Ràng buộc đến từ lời người dùng: "quanh đây" là ràng buộc, "X ở đâu" thì không.
    Toạ độ chính xác chỉ được giải ở ĐÂY, ngay lúc gọi — không quay lại lịch sử hội thoại.
    """
    # Dependency lấy từ ctx thay vì tham số rời — hợp đồng feature chỉ truyền (reg, ctx).
    places, location = ctx.places, ctx.location
    browser, bus = ctx.browser, ctx.bus
    speak_limit = config.PLACES_LIMIT

    from features.places.explain import explain
    from features.places.refine import (CHANGES, apply_refinement, needs_requery,
                                      radius_factor)
    from services.browser_protocol import summarize_places, build_open_or_reuse

    # Trạng thái lượt tìm gần nhất — nền cho việc tinh chỉnh ở lượt sau.
    # Giữ CẢ ứng viên lẫn ngữ cảnh: "có chỗ nào mở muộn hơn không" phải lọc trên đúng
    # danh sách đó, không được tra lại bằng từ khoá mới.
    session = {"results": [], "query": None, "area": None, "center": None,
               "radius_km": None, "rank_ctx": {}}

    def _origin(near):
        """Giải điểm tra cứu -> ((lat,lng), tên hiển thị) hoặc (None, câu hỏi lại)."""
        text = (near or "").strip()
        if not text or text == "@current":
            coords = location.coords()
            if not coords:
                return None, ("Tôi chưa biết bạn đang ở khu vực nào. Bạn cho tôi biết "
                              "quận/thành phố nhé, tôi sẽ nhớ cho lần sau.")
            return coords, location.display()
        spot = places.resolve_area(text, origin=location.coords())
        if not spot:
            return None, (f"Tôi chưa xác định được '{text}' nằm ở đâu. Bạn cho tôi biết "
                          f"quận hoặc thành phố nhé, tôi tìm quanh đó.")
        return (spot[0], spot[1]), spot[2]

    def _remember(out, query, area=None, center=None, radius_km=None):
        # Chỉ giữ danh sách khi THỰC SỰ có kết quả — tránh 'mở cái thứ 2' trỏ vào lượt cũ.
        ok = out["outcome"] == "OK"
        session["results"] = out["results"] if ok else []
        session["query"] = query if ok else None
        session["area"] = (area or out.get("area")) if ok else None
        session["center"] = center if ok else None
        session["radius_km"] = radius_km if ok else None
        session["rank_ctx"] = ((out.get("diagnostics") or {}).get("rank_ctx") or {}) if ok else {}
        # Giải thích CHỈ dựng từ bằng chứng có thật; LLM chỉ đọc lại, không thêm.
        reason = None
        if out["outcome"] == "OK" and out["results"]:
            reason = explain(out["results"][0],
                             (out.get("diagnostics") or {}).get("rank_ctx") or {})
        return summarize_places(out["outcome"], out["results"], query,
                                out.get("diagnostics"), area=area or out.get("area"),
                                source=out.get("source"), speak_limit=speak_limit,
                                top_reason=reason)

    def find_nearby(query=None, near=None, radius_km=None):
        if not query or not str(query).strip():
            return "Bạn muốn tìm loại địa điểm nào quanh đó?"
        coords, label = _origin(near)
        if coords is None:
            return label
        try:
            r = float(radius_km) if radius_km else None
        except (TypeError, ValueError):
            r = None
        out = places.find_nearby(str(query).strip(), coords, radius_km=r)
        return _remember(out, str(query).strip(), area=None if not near else label,
                         center=coords, radius_km=r or places.radius_km)

    def find_place(name=None, in_area=None):
        if not name or not str(name).strip():
            return "Bạn muốn tìm chỗ nào?"
        area = (in_area or "").strip()
        out = places.find_place(str(name).strip(), origin=location.coords(),
                                area=area or None)
        if out.get("diagnostics", {}).get("unknown_area"):
            return (f"Tôi chưa xác định được '{area}' nằm ở đâu. Bạn nói rõ quận hoặc "
                    f"thành phố giúp tôi nhé.")
        if out["outcome"] == "SOURCE_UNAVAILABLE" and not area \
                and out.get("diagnostics", {}).get("reason"):
            return ("Tôi chưa biết bạn đang ở đâu để tra. Bạn cho tôi biết quận/thành phố "
                    "nhé, hoặc nói rõ tìm ở khu vực nào.")
        return _remember(out, str(name).strip(), area=out.get("area"))

    def _browser_search(query, limit=8):
        """Dự phòng cho discovery: đọc trang kết quả trong TRÌNH DUYỆT THẬT -> [url].

        Cần vì mọi máy tìm kiếm qua HTTP thẳng đều chặn sau một buổi gọi liên tục từ cùng
        một IP. Trình duyệt thật không bị chặn vì nó là trình duyệt thật — chậm hơn, nhưng
        giữ tính năng sống thay vì chết lặng.
        """
        if browser is None or not getattr(browser, "connected", False):
            return []
        from services.browser_protocol import build_search_read, parse_search_results
        try:
            cmd = build_search_read(query, config.WEB_SEARCH_ENGINE, limit=limit)
            resp = browser.send_command(timeout=25, **cmd)
        except Exception as e:
            logger.warning("research: discovery qua trình duyệt lỗi: %s", e)
            return []
        results, err = parse_search_results(resp)
        if err:
            logger.warning("research: discovery qua trình duyệt: %s", err)
            return []
        return [r["url"] for r in results if r.get("url")]

    def _claim_cache():
        """ClaimCache dùng chung cho lane research, TẠO LƯỜI.

        Lười vì phiên nào không hỏi địa điểm thì không phải đọc file nào — cùng lý lẽ với
        panel kết quả. Dựng hỏng thì trả None: mất phần tăng tốc, không mất tính năng.
        """
        if "claim_cache" not in session:
            store = None
            if config.RESEARCH_CACHE_ENABLED:
                try:
                    from research.claim_cache import DEFAULT_PATH, ClaimCache
                    store = ClaimCache(config.RESEARCH_CACHE_PATH or DEFAULT_PATH,
                                       fresh_hours=config.RESEARCH_CACHE_FRESH_H,
                                       ttl_days=config.RESEARCH_CACHE_TTL_DAYS)
                except Exception as e:
                    logger.warning("research: không dựng được claim cache: %s", e)
            session["claim_cache"] = store
        return session["claim_cache"]

    def research_places(need=None, in_area=None):
        """Tìm theo NHU CẦU chứ không theo loại.

        Chậm hơn `find_nearby` nhiều lần vì phải đọc web, nên chỉ dùng khi ràng buộc KHÔNG
        có trường dữ liệu nào trên bản đồ ("nhiều cây xanh", "phong cách cổ"). Ném thẳng
        những câu đó vào Maps là vô nghĩa một cách im lặng: Maps ÉP KHỚP thay vì trả rỗng.
        """
        from features.places.deep_research import research, say_research
        if not need or not str(need).strip():
            return "Bạn muốn tìm chỗ như thế nào?"
        area = (in_area or "").strip() or location.coarse("province") or None
        out = research(str(need).strip(), area=area, places=places,
                       origin=location.coords(), browser_search=_browser_search,
                       cache=_claim_cache())

        # Giữ ứng viên cho "mở cái thứ N", nhưng KHÔNG đặt `center`/`query`: nhánh tra lại
        # của `refine_places` sẽ ném nguyên câu nhu cầu vào Maps như từ khoá. Thiếu `center`
        # thì nhánh đó dừng và hỏi lại, an toàn hơn.
        ok = out["outcome"] == "OK"
        session["results"] = out["results"] if ok else []
        session["query"] = None
        session["area"] = area if ok else None
        session["center"] = None
        session["radius_km"] = None
        session["rank_ctx"] = {}

        # Panel là tầng KIỂM CHỨNG BẰNG MẮT cho thuộc tính không đo được.
        # Giọng nói đọc 3 chỗ đầu; panel hiện đủ danh sách kèm bằng chứng xem được.
        if bus is not None:
            bus.emit_places(out["results"], need=str(need).strip())
        return say_research(out, str(need).strip(), speak_limit=speak_limit)

    def open_place_result(index=None):
        results = session["results"]
        if not results:
            return "Chưa có danh sách địa điểm nào để mở — hãy tìm trước đã."
        try:
            i = int(str(index).strip())
        except (TypeError, ValueError):
            return "Cần cho biết số thứ tự chỗ cần mở (ví dụ 1, 2, 3)."
        if i < 1 or i > len(results):
            return f"Chỉ có {len(results)} chỗ, không có số {i}."
        chosen = results[i - 1]

        # Lane 3 trả ứng viên CHƯA tra bản đồ (giải toạ độ lười — xem
        # `place_research.DEFAULT_RESOLVE_LIMIT`). Đây đúng là lúc trả khoản nợ đó: người
        # dùng đã chọn một chỗ cụ thể, nên bỏ ~12 giây tra một chỗ là xứng đáng, khác hẳn
        # việc tra sẵn cả danh sách mà phần lớn không ai mở.
        if not chosen.get("url") and chosen.get("resolved") is False:
            out = places.find_place(chosen["name"], origin=location.coords())
            if out.get("outcome") == "OK" and out.get("results"):
                chosen = dict(chosen, **out["results"][0])
                chosen["resolved"] = True
                results[i - 1] = chosen          # nhớ lại, khỏi tra lần hai
            else:
                where = f" (địa chỉ ghi trên bài: {chosen['address']})" if chosen.get("address") else ""
                return (f"Tôi chưa tra được '{chosen['name']}' trên bản đồ{where}.")

        if browser is not None and chosen.get("url"):
            browser.send_command(**build_open_or_reuse(chosen["url"]))
            return f"Đang mở chỗ số {i}: {chosen['name']}."
        return f"Chỗ số {i} là {chosen['name']}."

    _REFINE_LABEL = {"open_later": "mở muộn hơn", "open_now": "đang mở cửa",
                     "closer": "gần hơn", "cheaper": "rẻ hơn",
                     "better_rated": "đánh giá cao hơn", "quieter": "yên tĩnh hơn",
                     "farther": "tìm rộng ra"}

    def refine_places(change=None, value=None):
        import datetime as _dt
        if not session["results"]:
            return "Chưa có danh sách địa điểm nào để lọc — bạn muốn tìm gì trước đã?"
        ch = (change or "").strip().lower()
        if ch not in CHANGES:
            return ("Bạn muốn đổi theo hướng nào: mở muộn hơn, gần hơn, rẻ hơn, "
                    "đánh giá cao hơn, hay yên tĩnh hơn?")

        if needs_requery(ch):
            # Mở rộng phạm vi thì buộc phải tra lại — không bịa ra ứng viên mới.
            center = session["center"]
            if not center:
                return "Bạn nhắc lại giúp tôi tìm gì và ở khu vực nào nhé."
            base = session["radius_km"] or places.radius_km
            new_r = max(0.3, min(30.0, base * radius_factor(ch)))
            out = places.find_nearby(session["query"], center, radius_km=new_r)
            return _remember(out, session["query"], area=session["area"],
                             center=center, radius_km=new_r)

        # Dùng giờ HIỆN TẠI, không dùng giờ của lượt tìm trước: hội thoại có thể đã kéo
        # dài, và "còn mở bao lâu nữa" phụ thuộc lúc HỎI.
        kept, meta = apply_refinement(session["results"], ch, value, now=_dt.datetime.now(),
                                      radius_km=session["radius_km"])
        label = _REFINE_LABEL.get(ch, ch)
        if not kept:
            # Giữ nguyên danh sách cũ để người dùng còn lọc kiểu khác được.
            note = meta.get("note") or f"Không có chỗ nào {label}."
            return note + " Bạn có muốn tôi tìm rộng ra không?"

        session["results"] = kept
        reason = explain(kept[0], session.get("rank_ctx") or {})
        head = summarize_places("OK", kept, f"{session['query']} ({label})",
                                area=session.get("area"), speak_limit=speak_limit,
                                top_reason=reason)
        return (meta["note"] + "\n" + head) if meta.get("note") else head

    def set_my_location(place=None):
        if not place or not str(place).strip():
            return "Bạn đang ở khu vực nào?"
        # Dùng CHUNG bộ giải địa danh hai tầng với find_nearby: danh bạ hành chính không
        # biết khu đô thị / toà nhà, nhưng bản đồ thì biết.
        spot = places.resolve_area(str(place).strip())
        if not spot:
            return (f"Tôi chưa xác định được '{place}' ở đâu. Bạn nói tên quận hoặc "
                    f"thành phố giúp tôi nhé.")
        shown = location.set_coords(spot[0], spot[1], spot[2])
        return f"Tôi nhớ rồi, bạn đang ở {shown}."

    reg.register(Tool(
        name="find_nearby",
        description=("Tìm địa điểm theo LOẠI ở gần một vị trí (quán ăn, cà phê, ATM, hiệu "
                     "thuốc, cây xăng...). Dùng khi người dùng hỏi 'quanh đây có...', 'gần "
                     "đây có...', 'chỗ nào gần tôi...'. KHÔNG dùng khi người dùng nêu TÊN "
                     "RIÊNG của một chỗ cụ thể mà không kèm 'gần đây' — khi đó dùng find_place."),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Loại địa điểm, ví dụ 'quán cà phê'"},
                "near": {"type": "string",
                         "description": "Khu vực người dùng nêu; để trống = vị trí hiện tại"},
                "radius_km": {"type": "number",
                              "description": "Chỉ đặt khi người dùng nói rõ, ví dụ 'trong 2 km'"},
            },
            "required": ["query"],
        },
        handler=find_nearby,
        speakable=True,
    ))

    reg.register(Tool(
        name="find_place",
        description=("Tìm ĐÚNG MỘT địa điểm mà người dùng gọi TÊN (ví dụ 'nhà sách Fahasa "
                     "Nguyễn Văn Cừ', 'quán Highlands Trần Duy Hưng'). KHÔNG giới hạn khoảng "
                     "cách trừ khi người dùng nêu khu vực trong `in_area`. Nếu câu có 'gần "
                     "đây/quanh đây' thì dùng find_nearby thay vì tool này."),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tên chỗ cần tìm"},
                "in_area": {"type": "string",
                            "description": "Khu vực người dùng nêu, ví dụ 'quận 9'; để trống nếu không nêu"},
            },
            "required": ["name"],
        },
        handler=find_place,
        speakable=True,
    ))

    reg.register(Tool(
        name="research_places",
        # Mô tả này là thứ model dùng để CHỌN LANE, nên con số thời gian trong đó phải
        # đúng với hiện trạng: nói quá chậm thì model né tool, nói "nhanh, cứ dùng" thì nó
        # thành lane mặc định. Luật chọn lane vẫn là: KHÔNG diễn đạt được bằng loại +
        # khoảng cách thì mới dùng tool này.
        description=("Tìm địa điểm theo MÔ TẢ/CẢM GIÁC mà bản đồ không có trường dữ liệu: "
                     "'quán cà phê nhiều cây xanh', 'quán phong cách cổ', 'quán view đẹp "
                     "để dẫn người yêu đi', 'chỗ nào decor xinh'. Tool này ĐỌC BÁO/BLOG "
                     "(khoảng 5 giây) và trả về chỗ được NHIỀU NGUỒN nhắc tới, kèm ảnh và "
                     "trích dẫn — nhưng KHÔNG lọc theo khoảng cách. Chỉ dùng khi yêu cầu "
                     "KHÔNG diễn đạt được bằng loại địa điểm + khoảng cách; hỏi 'quán cà "
                     "phê gần đây' thì dùng find_nearby."),
        input_schema={
            "type": "object",
            "properties": {
                "need": {"type": "string",
                         "description": "Nguyên văn mô tả của người dùng, ví dụ 'quán cà phê nhiều cây xanh'"},
                "in_area": {"type": "string",
                            "description": "Khu vực người dùng nêu; để trống = khu vực đang ở"},
            },
            "required": ["need"],
        },
        handler=research_places,
        speakable=True,
    ))

    reg.register(Tool(
        name="open_place_result",
        description=("Mở một chỗ trong danh sách vừa đọc, theo SỐ THỨ TỰ (1, 2, 3...). "
                     "Dùng sau find_nearby hoặc find_place."),
        input_schema={
            "type": "object",
            "properties": {"index": {"type": "integer", "description": "Số thứ tự"}},
            "required": ["index"],
        },
        handler=open_place_result,
        speakable=True,
    ))

    reg.register(Tool(
        name="refine_places",
        description=("Lọc lại DANH SÁCH ĐỊA ĐIỂM vừa đọc theo một yêu cầu mới, KHÔNG tìm "
                     "lại từ đầu. Dùng khi người dùng nói kiểu 'có chỗ nào mở muộn hơn "
                     "không', 'gần hơn nữa đi', 'rẻ hơn', 'chỗ nào yên tĩnh hơn', 'chỗ "
                     "nào điểm cao hơn', 'tìm rộng ra'. KHÔNG được đưa những từ này vào "
                     "find_nearby như từ khoá tìm kiếm — chúng là RÀNG BUỘC, không phải "
                     "tên quán."),
        input_schema={
            "type": "object",
            "properties": {
                "change": {"type": "string",
                           "enum": ["open_later", "open_now", "closer", "cheaper",
                                    "better_rated", "quieter", "farther"],
                           "description": "Hướng tinh chỉnh"},
                "value": {"type": "string",
                          "description": "Mốc cụ thể nếu người dùng nói rõ, vd '23' cho "
                                         "'mở tới 23 giờ'; để trống nếu không nói"},
            },
            "required": ["change"],
        },
        handler=refine_places,
        speakable=True,
    ))

    reg.register(Tool(
        name="set_my_location",
        description=("Ghi nhớ khu vực người dùng đang ở (quận/thành phố) để lần sau hỏi "
                     "'quanh đây' là biết. Dùng khi người dùng nói họ đang ở đâu."),
        input_schema={
            "type": "object",
            "properties": {"place": {"type": "string", "description": "Tên quận/thành phố"}},
            "required": ["place"],
        },
        handler=set_my_location,
        speakable=True,
    ))
