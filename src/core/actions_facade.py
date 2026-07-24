"""
Facade gom mọi "hành động" (action) của trợ lý sau một interface duy nhất.

Mục đích: Agent/tools (core/tools.py) chỉ phụ thuộc vào facade này thay vì import
trực tiếp các hàm điều khiển hệ thống. Nhờ vậy khi test có thể truyền một facade
giả (fake/mock) — không thực sự mở app, đổi âm lượng hay tắt máy.

Mặc định `AssistantActions()` nối tới các hàm thật trong package `actions`.
"""

from actions.app_control import open_application, close_application
from actions.system_control import (
    control_volume,
    control_brightness,
    system_shutdown,
    system_restart,
)
from actions.web_search import (
    search_web,
    open_website,
    search_and_play_youtube,
    search_and_play_youtube_direct,
    search_on_specific_site,
)
from actions.system_info import get_system_summary


class AssistantActions:
    """Bọc các hàm action thật. Test có thể thay bằng đối tượng cùng interface."""

    # --- Ứng dụng ---
    def open_application(self, app_name):
        return open_application(app_name)

    def close_application(self, app_name):
        return close_application(app_name)

    # --- Hệ thống ---
    def control_volume(self, level=None, change=None):
        return control_volume(level=level, change=change)

    def control_brightness(self, level=None, change=None):
        return control_brightness(level=level, change=change)

    def system_shutdown(self, close_apps=True):
        return system_shutdown(close_apps=close_apps)

    def system_restart(self, close_apps=True):
        return system_restart(close_apps=close_apps)

    def system_info(self, what="all"):
        return get_system_summary(what)

    # --- Web / YouTube ---
    def open_website(self, website_name):
        return open_website(website_name)

    def search_web(self, query, engine="google"):
        return search_web(query, engine)

    def search_and_play_youtube(self, query):
        return search_and_play_youtube(query)

    def search_and_play_youtube_direct(self, query):
        return search_and_play_youtube_direct(query)

    def search_on_specific_site(self, query, site):
        return search_on_specific_site(query, site)
