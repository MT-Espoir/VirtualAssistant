from features.salm.app_identity import is_classifiable_app_id
from features.salm.windows import WindowsActivityProbe, _window_is_user_facing


def _window(**overrides):
    values = dict(
        visible=True,
        iconic=False,
        cloaked=False,
        is_shell=False,
        class_name="EditorWindow",
        ex_style=0,
        has_owner=False,
        width=1200,
        height=800,
    )
    values.update(overrides)
    return _window_is_user_facing(**values)


def test_window_filter_accepts_visible_and_minimized_application_windows():
    assert _window()
    assert _window(visible=False, iconic=True)


def test_window_filter_rejects_hidden_cloaked_shell_and_worker_windows():
    assert not _window(visible=False, iconic=False)
    assert not _window(cloaked=True)
    assert not _window(is_shell=True)
    assert not _window(class_name="Shell_TrayWnd")
    assert not _window(width=0)


def test_window_filter_rejects_tool_and_owned_popup_unless_marked_app_window():
    ws_ex_toolwindow = 0x00000080
    ws_ex_appwindow = 0x00040000
    assert not _window(ex_style=ws_ex_toolwindow)
    assert not _window(has_owner=True)
    assert _window(ex_style=ws_ex_toolwindow | ws_ex_appwindow)
    assert _window(has_owner=True, ex_style=ws_ex_appwindow)


def test_running_apps_uses_only_window_foreground_and_media_evidence(monkeypatch):
    monkeypatch.setattr(
        WindowsActivityProbe, "_window_app_ids",
        staticmethod(lambda: frozenset(("code", "chrome"))),
    )

    apps = WindowsActivityProbe._running_apps(
        foreground_app="explorer",
        media_apps=frozenset(("spotify", "chrome")),
    )

    assert apps == frozenset(("code", "chrome", "explorer", "spotify"))


def test_running_apps_rejects_windows_surfaces_even_with_foreground_or_media_evidence(
        monkeypatch):
    monkeypatch.setattr(
        WindowsActivityProbe, "_window_app_ids",
        staticmethod(lambda: frozenset(("code",))),
    )

    apps = WindowsActivityProbe._running_apps(
        foreground_app="lockapp",
        media_apps=frozenset(("svchost", "spotify")),
    )

    assert apps == frozenset(("code", "spotify"))


def test_running_apps_does_not_enumerate_services_or_background_processes(monkeypatch):
    monkeypatch.setattr(
        WindowsActivityProbe, "_window_app_ids",
        staticmethod(lambda: frozenset(("code",))),
    )

    def fail_if_process_inventory_is_read(*args, **kwargs):
        raise AssertionError("process inventory must not be an app candidate source")

    monkeypatch.setattr("features.salm.windows.psutil.process_iter",
                        fail_if_process_inventory_is_read)

    assert WindowsActivityProbe._running_apps() == frozenset(("code",))


def test_generic_host_processes_are_visible_but_not_classifiable():
    assert is_classifiable_app_id("code") is True
    assert is_classifiable_app_id("python") is False
    assert is_classifiable_app_id("node") is False
    assert is_classifiable_app_id("svchost") is False
