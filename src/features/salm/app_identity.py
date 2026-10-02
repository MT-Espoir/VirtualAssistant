"""Shared SALM app-identity policy used by live collection and legacy migration."""


OS_SURFACE_APPS = frozenset((
    "applicationframehost", "audiodg", "csrss", "dwm", "fontdrvhost",
    "lockapp", "logonui", "memory-compression", "registry", "runtimebroker",
    "searchhost", "services", "shellexperiencehost", "sihost", "smss",
    "startmenuexperiencehost", "svchost", "system", "system-idle-process",
    "taskhostw", "textinputhost", "wininit", "winlogon",
))

# Tên executable chung không đủ để gán một ngữ cảnh duy nhất. Ví dụ ``python`` có thể
# là chính trợ lý, một script, GUI hay terminal. Vẫn hiển thị trong analytics cũ, nhưng
# không cho nó tham gia coverage/workload cho tới khi collector có identity cụ thể hơn.
AMBIGUOUS_HOST_APPS = frozenset((
    "electron", "java", "javaw", "node", "python", "pythonw",
))

_DISPLAY_NAMES = {
    "chrome": "Google Chrome",
    "code": "Visual Studio Code",
    "discord": "Discord",
    "explorer": "File Explorer",
    "firefox": "Mozilla Firefox",
    "ms-teams": "Microsoft Teams",
    "msedge": "Microsoft Edge",
    "notepad": "Notepad",
    "obsidian": "Obsidian",
    "pycharm64": "PyCharm",
    "spotify": "Spotify",
    "vlc": "VLC media player",
    "zoom": "Zoom",
    "chatgpt": "ChatGPT",
}


def is_user_facing_app_id(app_id):
    return bool(app_id and app_id not in OS_SURFACE_APPS)


def is_classifiable_app_id(app_id):
    value = str(app_id or "").strip().casefold()
    return bool(is_user_facing_app_id(value) and value not in AMBIGUOUS_HOST_APPS)


def display_app_name(app_id):
    """Stable full label for UI; unknown IDs remain recognizable and unaliased."""
    raw = str(app_id or "").strip()
    if not raw:
        return "(không rõ tên)"
    known = _DISPLAY_NAMES.get(raw.casefold())
    if known:
        return known
    return " ".join(part[:1].upper() + part[1:]
                    for part in raw.replace("_", "-").split("-") if part) or raw


def sanitize_legacy_daily_metrics(metrics, schema_version):
    """Remove v1 process-inventory pollution from imported daily projections."""
    metrics = dict(metrics or {})
    if int(schema_version or 1) >= 2:
        return metrics
    apps = metrics.get("apps") or {}

    def positive(value):
        try:
            return float(value or 0) > 0
        except (TypeError, ValueError):
            return False

    metrics["apps"] = {
        app_id: values for app_id, values in apps.items()
        if is_user_facing_app_id(app_id)
        and any(positive((values or {}).get(field)) for field in (
            "foreground", "interactive", "passive_viewing", "background_audio"))
    }
    return metrics
