"""Test tra cứu thời tiết (actions.weather) — http_get giả, không cần mạng."""

import json

try:
    import pytest
except ImportError:
    pytest = None

from actions import weather
from actions.weather import get_weather, geocode, _advice


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _fake_http(geo=None, forecast=None):
    """Trả hàm http_get(url) phân biệt geocode vs forecast theo URL."""
    def _get(url):
        if "geocoding-api" in url:
            return _FakeResp(geo if geo is not None else {"results": []})
        return _FakeResp(forecast if forecast is not None else {})
    return _get


_HANOI_GEO = {"results": [{"latitude": 21.02, "longitude": 105.84,
                           "name": "Hà Nội", "country": "Việt Nam"}]}


def _forecast(code=0, cur_temp=34, tmax=36, tmin=27, rain=80, uv=9):
    return {
        "current": {"temperature_2m": cur_temp, "weather_code": code},
        "daily": {
            "weather_code": [code],
            "temperature_2m_max": [tmax], "temperature_2m_min": [tmin],
            "precipitation_probability_max": [rain], "uv_index_max": [uv],
        },
    }


# --------------------------- geocode --------------------------- #

def test_geocode_returns_first_result():
    place = geocode("Hà Nội", http_get=_fake_http(geo=_HANOI_GEO))
    assert place["latitude"] == 21.02 and place["name"] == "Hà Nội"


def test_geocode_not_found_returns_none():
    assert geocode("xyzkhongco", http_get=_fake_http(geo={"results": []})) is None


def test_geocode_error_returns_none():
    def boom(url):
        raise RuntimeError("mạng lỗi")
    assert geocode("Hà Nội", http_get=boom) is None


# --------------------------- get_weather --------------------------- #

def test_weather_summary_has_place_temp_and_source():
    out = get_weather("Hà Nội", http_get=_fake_http(_HANOI_GEO, _forecast()))
    assert "Hà Nội" in out
    assert "36" in out and "27" in out          # nhiệt độ cao/thấp nhất
    assert "Open-Meteo" in out                    # ghi nguồn CC BY 4.0


def test_weather_high_uv_and_rain_advice():
    out = get_weather("Hà Nội", http_get=_fake_http(_HANOI_GEO, _forecast(uv=9, rain=80)))
    assert "UV" in out and "che chắn" in out.lower()
    assert "áo mưa" in out.lower()


def test_weather_calm_day_no_alarm_advice():
    # UV thấp + ít mưa -> không có khuyến nghị che chắn/áo mưa
    out = get_weather("Đà Lạt",
                      http_get=_fake_http(_HANOI_GEO, _forecast(code=1, cur_temp=20,
                                          tmax=24, tmin=15, rain=10, uv=3)))
    assert "áo mưa" not in out.lower() and "che chắn" not in out.lower()


def test_weather_place_not_found():
    out = get_weather("khongcothatdau", http_get=_fake_http(geo={"results": []}))
    assert "Không tìm thấy" in out


def test_weather_empty_location():
    assert "Cần cho biết địa điểm" in get_weather("", http_get=_fake_http())


def test_weather_forecast_error_handled():
    def _get(url):
        if "geocoding-api" in url:
            return _FakeResp(_HANOI_GEO)
        raise RuntimeError("timeout")
    out = get_weather("Hà Nội", http_get=_get)
    assert "Không lấy được dữ liệu thời tiết" in out


# --------------------------- ngưỡng khuyến nghị --------------------------- #

def test_advice_thresholds():
    # UV rất cao + mưa cao
    tips = _advice(uv_max=10, rain_prob=85, temp_max=30, code=61)
    joined = " ".join(tips).lower()
    assert "rất cao" in joined and "áo mưa" in joined
    # Ngày dịu: không cảnh báo
    assert _advice(uv_max=2, rain_prob=5, temp_max=22, code=1) == []
    # Nóng gắt trời quang
    assert any("nóng" in t for t in _advice(uv_max=7, rain_prob=0, temp_max=37, code=0))


if __name__ == "__main__":
    if pytest is not None:
        raise SystemExit(pytest.main([__file__, "-v"]))
    failures = 0
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            try:
                _fn()
                print("PASS", _name)
            except Exception as _e:  # noqa: BLE001
                failures += 1
                print("FAIL", _name, "->", repr(_e))
    print(f"\n{'ALL PASS' if not failures else str(failures) + ' FAILED'}")
    raise SystemExit(1 if failures else 0)
