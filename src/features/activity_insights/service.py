"""Deterministic, local-only analytics over privacy-reduced SALM daily data."""

import json
import threading
from datetime import datetime, timedelta

from features.salm.app_identity import display_app_name, is_classifiable_app_id


PERIOD_DAYS = {"today": 1, "7_days": 7, "30_days": 30}
VIEWS = frozenset(("overview", "apps", "focus", "trend"))
CATEGORIES = frozenset(("work", "communication", "media", "personal", "unknown"))


def _seconds(value):
    try:
        return round(max(0.0, float(value or 0)), 3)
    except (TypeError, ValueError):
        return 0.0


class ActivityInsightsService:
    """Aggregate at most 30 daily rows; never reads or exposes raw SALM events."""

    def __init__(self, database, now_provider=None, clear_history=None):
        self.database = database
        self._now = now_provider or (lambda: datetime.now().astimezone())
        self._clear_history = clear_history or database.clear_salm_activity
        self._query_lock = threading.Lock()
        self._last_query = ("7_days", "overview")

    def _preferences(self):
        return {row["app_id"]: row
                for row in self.database.list_salm_app_preferences()}

    def last_query(self):
        with self._query_lock:
            return self._last_query

    def snapshot(self, period="today", view="overview"):
        period = str(period or "today").strip().lower()
        view = str(view or "overview").strip().lower()
        if period not in PERIOD_DAYS:
            raise ValueError(f"Khoảng thời gian không hợp lệ: {period}")
        if view not in VIEWS:
            raise ValueError(f"Góc nhìn không hợp lệ: {view}")
        with self._query_lock:
            self._last_query = (period, view)

        now = self._now()
        today = now.date()
        start = today - timedelta(days=PERIOD_DAYS[period] - 1)
        rows = self.database.salm_daily_range(start.isoformat(), today.isoformat())
        by_day = {str(row["day"]): row for row in rows}
        preferences = self._preferences()

        totals = {
            "interactive_seconds": 0.0,
            "screen_exposure_seconds": 0.0,
            "work_engagement_seconds": 0.0,
            "confirmed_break_seconds": 0.0,
            "unknown_seconds": 0.0,
        }
        apps = {}
        trend = []
        partial_days = 0

        for offset in range(PERIOD_DAYS[period]):
            day = start + timedelta(days=offset)
            key = day.isoformat()
            row = by_day.get(key)
            metrics = (row or {}).get("metrics") or {}
            interactive = 0.0
            for raw_app_id, durations in (metrics.get("apps") or {}).items():
                app_id = str(raw_app_id).strip().casefold()
                if not app_id:
                    continue
                preference = preferences.get(app_id) or {}
                if preference.get("excluded"):
                    continue
                value = _seconds((durations or {}).get("interactive"))
                interactive += value
                if value > 0:
                    apps[app_id] = apps.get(app_id, 0.0) + value

            totals["interactive_seconds"] += interactive
            totals["screen_exposure_seconds"] += _seconds(
                metrics.get("screen_exposure"))
            totals["work_engagement_seconds"] += _seconds(
                metrics.get("work_engagement"))
            totals["confirmed_break_seconds"] += _seconds(
                metrics.get("confirmed_break"))
            totals["unknown_seconds"] += _seconds(metrics.get("unknown_duration"))

            is_today = day == today
            if row is not None and is_today:
                partial_days += 1
            trend.append({
                "day": key,
                "interactive_seconds": round(interactive, 3),
                "has_data": row is not None,
                "complete": row is not None and not is_today,
            })

        totals = {key: round(value, 3) for key, value in totals.items()}
        eligible_seconds = 0.0
        classified_seconds = 0.0
        top_apps = [
            {"app_id": app_id, "display_name": display_app_name(app_id),
             "interactive_seconds": round(value, 3),
             "category": (preferences.get(app_id) or {}).get(
                 "category", "unknown"),
             "classifiable": is_classifiable_app_id(app_id)}
            for app_id, value in sorted(
                apps.items(), key=lambda item: (-item[1], item[0].casefold()))
        ]
        for row in top_apps:
            if not row["classifiable"]:
                continue
            eligible_seconds += row["interactive_seconds"]
            if row["category"] != "unknown":
                classified_seconds += row["interactive_seconds"]

        classification_apps = []
        app_ids = set(apps) | set(preferences)
        for app_id in sorted(app_ids, key=lambda value: (
                -apps.get(value, 0.0), value.casefold())):
            preference = preferences.get(app_id) or {}
            classification_apps.append({
                "app_id": app_id,
                "display_name": display_app_name(app_id),
                "interactive_seconds": round(apps.get(app_id, 0.0), 3),
                "category": preference.get("category", "unknown"),
                "excluded": bool(preference.get("excluded")),
                "source": preference.get("source"),
                "classifiable": is_classifiable_app_id(app_id),
            })
        valid_days = len(rows)
        updated_values = [row.get("updated_at") for row in rows if row.get("updated_at")]
        return {
            "period": period,
            "view": view,
            "range": {"start": start.isoformat(), "end": today.isoformat()},
            "generated_at": now.isoformat(timespec="seconds"),
            "updated_at": max(updated_values) if updated_values else None,
            "totals": totals,
            "top_apps": top_apps,
            "trend": trend,
            "data_quality": {
                "valid_days": valid_days,
                "partial_days": partial_days,
                "missing_days": PERIOD_DAYS[period] - valid_days,
                "coverage": round(valid_days / PERIOD_DAYS[period], 3),
                "unknown_seconds": totals["unknown_seconds"],
                "classification_coverage": round(
                    classified_seconds / eligible_seconds, 3)
                if eligible_seconds > 0 else 0.0,
                "classification_eligible_seconds": round(eligible_seconds, 3),
            },
            # Chỉ UI nhận danh sách quản lý này; ``llm_result`` cố ý không chuyển tiếp.
            "classification_apps": classification_apps,
        }

    def _known_app_ids(self):
        today = self._now().date()
        start = today - timedelta(days=89)
        known = {row["app_id"] for row in self.database.list_salm_app_preferences()}
        for row in self.database.salm_daily_range(start.isoformat(), today.isoformat()):
            known.update(str(app_id).casefold()
                         for app_id in ((row.get("metrics") or {}).get("apps") or {}))
        return known

    def set_app_preference(self, app_id, category="unknown", *, excluded=False,
                           source="user"):
        app_id = str(app_id or "").strip().casefold()
        category = str(category or "unknown").strip().lower()
        if app_id not in self._known_app_ids():
            raise ValueError("Ứng dụng này chưa xuất hiện trong dữ liệu Activity Insights.")
        if category not in CATEGORIES:
            raise ValueError("Nhóm ứng dụng không hợp lệ.")
        if category != "unknown" and not is_classifiable_app_id(app_id):
            raise ValueError("Tên tiến trình này quá chung để phân loại chính xác.")
        return self.database.upsert_salm_app_preference(
            app_id, category, excluded=excluded, source=source)

    def reset_app_preference(self, app_id):
        app_id = str(app_id or "").strip().casefold()
        if app_id not in self._known_app_ids():
            raise ValueError("Ứng dụng này chưa xuất hiện trong dữ liệu Activity Insights.")
        self.database.delete_salm_app_preference(app_id)
        return {"app_id": app_id, "category": "unknown", "excluded": False,
                "source": None}

    def apply_setting(self, action, app_id=None, category=None):
        action = str(action or "").strip().lower()
        app_id = str(app_id or "").strip().casefold()
        if action == "clear_history":
            return {"action": action, "removed": self.clear_activity_history()}
        if action == "reset":
            return {"action": action,
                    "preference": self.reset_app_preference(app_id)}
        current = self.database.salm_app_preference(app_id) or {
            "category": "unknown", "excluded": False}
        if action == "classify":
            current_category = category
            excluded = False
        elif action == "exclude":
            current_category = current["category"]
            excluded = True
        elif action == "include":
            current_category = current["category"]
            excluded = False
        else:
            raise ValueError("Thao tác Activity Insights không hợp lệ.")
        preference = self.set_app_preference(
            app_id, current_category, excluded=excluded, source="user")
        return {"action": action, "preference": preference}

    def clear_activity_history(self):
        return self._clear_history()

    def refresh_snapshot(self):
        period, view = self.last_query()
        return self.snapshot(period, view)

    @staticmethod
    def llm_result(snapshot):
        """Small aggregate-only payload for the Agent's persona-aware final wording."""
        quality = snapshot.get("data_quality") or {}
        if not quality.get("valid_days"):
            return json.dumps({
                "status": "no_data",
                "period": snapshot.get("period"),
                "message": "Chưa có dữ liệu hoạt động trong khoảng thời gian này.",
            }, ensure_ascii=False, separators=(",", ":"))

        totals = snapshot.get("totals") or {}
        payload = {
            "status": "ok",
            "period": snapshot.get("period"),
            "range": snapshot.get("range"),
            "totals": {
                key: totals.get(key, 0) for key in (
                    "interactive_seconds", "screen_exposure_seconds",
                    "work_engagement_seconds", "confirmed_break_seconds")
            },
            "top_apps": [{
                key: row.get(key) for key in (
                    "app_id", "display_name", "interactive_seconds", "category")
            } for row in list(snapshot.get("top_apps") or [])[:5]],
            "trend": list(snapshot.get("trend") or []),
            "data_quality": quality,
            "note": "Đây là số liệu activity đã ghi nhận, không phải kết luận về người dùng.",
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
