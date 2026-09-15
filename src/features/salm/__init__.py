"""SALM — quan sát activity/app lifecycle cục bộ, không phải bề mặt tool của LLM.

Package này sở hữu toàn bộ collector, reducer, metrics và storage của SALM. `app.py`
chỉ dựng/tắt `SalmRuntime`; SALM cố ý không nằm trong catalog tool vì không có hành
động nào người dùng cần yêu cầu qua LLM.
"""

__all__ = ["InterventionGate", "ProactiveDispatcher", "SalmRuntime"]


def __getattr__(name):
    """Giữ package import nhẹ: avatar chỉ cần presenter không kéo collector Win32 vào."""
    if name in ("InterventionGate", "ProactiveDispatcher"):
        from features.salm.intervention import InterventionGate, ProactiveDispatcher
        return {"InterventionGate": InterventionGate,
                "ProactiveDispatcher": ProactiveDispatcher}[name]
    if name == "SalmRuntime":
        from features.salm.runtime import SalmRuntime
        return SalmRuntime
    raise AttributeError(name)
