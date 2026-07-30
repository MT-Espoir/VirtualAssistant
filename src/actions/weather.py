"""
Tra cứu thời tiết qua Open-Meteo (miễn phí, KHÔNG cần API key).

Dữ liệu thời tiết bởi Open-Meteo.com — giấy phép CC BY 4.0
  https://open-meteo.com/  |  https://creativecommons.org/licenses/by/4.0/
Khi dùng lại dữ liệu phải ghi nguồn; các câu trả lời sinh ra kèm "(Nguồn: Open-Meteo)".

Luồng: geocode(tên địa điểm) -> (lat, lon) -> forecast -> tóm tắt + khuyến nghị.
Ngưỡng khuyến nghị (UV, xác suất mưa, nhiệt độ) tính TRONG CODE cho tất định — LLM chỉ
diễn đạt lại, không phải tự suy luận (hợp với model local yếu). `http_get` tiêm được để
test không cần mạng.
"""

from urllib.parse import quote

from utils.logger import get_logger
from utils.text_norm import strip_accents

logger = get_logger(__name__)

_UA = "Mozilla/5.0 (VirtualAssistant)"
ATTRIBUTION = "Nguồn: Open-Meteo"      # ghi nguồn CC BY 4.0 (chi tiết ở docstring)

_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# Mã thời tiết WMO -> mô tả tiếng Việt (Open-Meteo dùng bảng mã WMO).
_WMO = {
    0: "trời quang, nắng", 1: "ít mây", 2: "có mây", 3: "nhiều mây",
    45: "sương mù", 48: "sương mù đóng băng",
    51: "mưa phùn nhẹ", 53: "mưa phùn", 55: "mưa phùn dày",
    56: "mưa phùn lạnh", 57: "mưa phùn lạnh dày",
    61: "mưa nhẹ", 63: "mưa vừa", 65: "mưa to",
    66: "mưa lạnh", 67: "mưa lạnh nặng hạt",
    71: "tuyết nhẹ", 73: "tuyết vừa", 75: "tuyết dày", 77: "hạt tuyết",
    80: "mưa rào nhẹ", 81: "mưa rào", 82: "mưa rào dữ dội",
    85: "mưa tuyết nhẹ", 86: "mưa tuyết dày",
    95: "dông", 96: "dông kèm mưa đá nhẹ", 99: "dông kèm mưa đá nặng",
}


def _get(url, params, http_get=None, timeout=15):
    """GET có tham số. `http_get(url)` tiêm được khi test (nhận URL đã ghép query)."""
    query = "&".join(f"{k}={quote(str(v))}" for k, v in params.items())
    full = f"{url}?{query}"
    if http_get is not None:
        return http_get(full)
    import requests
    return requests.get(full, timeout=timeout, headers={"User-Agent": _UA})


def geocode(location, http_get=None):
    """Tên địa điểm -> dict {latitude, longitude, name, country} hoặc None nếu không thấy.

    BỎ DẤU tiếng Việt ở truy vấn: Open-Meteo khớp địa danh kém với dấu ("Đà Lạt" cho
    kết quả sai, "Da Lat" đúng). Tên hiển thị vẫn lấy từ kết quả API (có dấu).
    """
    try:
        resp = _get(_GEOCODE_URL,
                    {"name": strip_accents(location), "count": 1,
                     "language": "vi", "format": "json"},
                    http_get)
        data = resp.json()
    except Exception as e:
        logger.error("weather: geocode lỗi cho '%s': %s", location, e)
        return None
    results = data.get("results") or []
    return results[0] if results else None


def _describe(code):
    return _WMO.get(code, "trời không rõ")


def _round(x):
    """Làm tròn số an toàn (None -> None)."""
    return None if x is None else round(x)


def _advice(uv_max, rain_prob, temp_max, code):
    """Khuyến nghị theo ngưỡng (tất định). Trả list các câu ngắn (có thể rỗng)."""
    tips = []
    # Nắng nóng
    if temp_max is not None and temp_max >= 35 and (code is None or code <= 3):
        tips.append("trời nắng nóng gay gắt, hạn chế ra ngoài giữa trưa và uống đủ nước")
    # Tia UV (thang UV Index quốc tế: 6-7 cao, 8-10 rất cao, 11+ cực cao)
    if uv_max is not None:
        if uv_max >= 8:
            tips.append(f"tia UV rất cao (chỉ số {_round(uv_max)}), cần che chắn kỹ, "
                        "đội mũ và bôi kem chống nắng khi ra ngoài")
        elif uv_max >= 6:
            tips.append(f"tia UV ở mức cao (chỉ số {_round(uv_max)}), nên che chắn khi ra ngoài")
    # Mưa
    if rain_prob is not None:
        if rain_prob >= 70:
            tips.append(f"khả năng mưa cao ({_round(rain_prob)}%), nhớ mang theo áo mưa hoặc ô")
        elif rain_prob >= 40:
            tips.append(f"có thể có mưa ({_round(rain_prob)}%), nên mang theo ô phòng khi")
    return tips


def get_weather(location, http_get=None):
    """Tra thời tiết hôm nay ở `location`, trả câu tóm tắt + khuyến nghị + ghi nguồn.

    Số liệu (nhiệt độ, mã thời tiết, xác suất mưa, UV) lấy từ Open-Meteo; phần khuyến
    nghị tính bằng ngưỡng trong code để tất định.
    """
    location = (location or "").strip()
    if not location:
        return "Cần cho biết địa điểm cần xem thời tiết."

    place = geocode(location, http_get)
    if not place:
        return f"Không tìm thấy địa điểm '{location}' để xem thời tiết."

    try:
        resp = _get(_FORECAST_URL, {
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": "temperature_2m,weather_code,apparent_temperature",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,uv_index_max",
            "timezone": "auto",
            "forecast_days": 1,
        }, http_get)
        data = resp.json()
    except Exception as e:
        logger.error("weather: forecast lỗi cho '%s': %s", location, e)
        return f"Không lấy được dữ liệu thời tiết: {e}"

    cur = data.get("current") or {}
    daily = data.get("daily") or {}

    def _first(key):
        vals = daily.get(key)
        return vals[0] if isinstance(vals, list) and vals else None

    code = cur.get("weather_code")
    if code is None:
        code = _first("weather_code")
    cur_temp = cur.get("temperature_2m")
    temp_max = _first("temperature_2m_max")
    temp_min = _first("temperature_2m_min")
    rain_prob = _first("precipitation_probability_max")
    uv_max = _first("uv_index_max")

    name = place.get("name") or location
    parts = [f"Thời tiết hôm nay ở {name}: {_describe(code)}"]
    if cur_temp is not None:
        parts.append(f", hiện khoảng {_round(cur_temp)}°C")
    if temp_max is not None and temp_min is not None:
        parts.append(f" (cao nhất {_round(temp_max)}°, thấp nhất {_round(temp_min)}°)")
    summary = "".join(parts) + "."

    tips = _advice(uv_max, rain_prob, temp_max, code)
    if tips:
        summary += " Khuyến nghị: " + "; ".join(tips) + "."

    return f"{summary} ({ATTRIBUTION})"
