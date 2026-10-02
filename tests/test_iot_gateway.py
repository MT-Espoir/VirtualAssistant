"""Contract and timing checks for the new gateway policy; no MQTT/camera hardware."""

from datetime import datetime, timedelta, timezone

from features.iot import core as core_module
from features.iot.core import IoTCore
from features.iot.registry import Device
from features.iot.settings import IoTSettings
from features.iot.storage import IoTStore


def _fixture(tmp_path, monkeypatch, *, automation=False, commands=False,
             protocol="v2"):
    clock = [datetime(2026, 9, 25, tzinfo=timezone.utc)]
    monkeypatch.setattr(core_module, "utc_now", lambda: clock[0])
    cfg = IoTSettings(
        mqtt_host="192.168.2.19", mqtt_port=1883,
        mqtt_username="", mqtt_password="", api_host="127.0.0.1",
        api_port=18787, token_path=tmp_path / "token",
        database_path=tmp_path / "iot.db", devices_path=tmp_path / "devices.json",
        commands_enabled=commands, automation_enabled=automation,
        alert_temperature_c=32, sensor_ttl_seconds=20,
        presence_ttl_seconds=10,
        command_protocol=protocol,
    )
    device = Device("node", "home", "bedroom", "node", "mqtt_node",
                    "home/node", ("temperature.read", "humidity.read", "climate.power"))
    store = IoTStore(cfg.database_path)
    sent = []

    def publish(topic, payload, qos, retain):
        sent.append((topic, payload, qos, retain))
        return True

    core = IoTCore(cfg, [device], store, publish)
    core.mqtt_connected = True
    return core, store, sent, clock


def _sample(core, sample, temperature, retained=False):
    payload = ("{\"temperature_c\":%s,\"humidity_percent\":60,\"sample\":%s}"
               % (temperature, sample)).encode()
    assert core.ingest("home/node/dht20/state", payload, retained=retained)


def test_retained_sample_does_not_appear_fresh_or_trigger_alert(tmp_path, monkeypatch):
    core, store, sent, _clock = _fixture(tmp_path, monkeypatch)
    try:
        _sample(core, 1, 34, retained=True)
        snapshot = core.snapshot()
        assert snapshot["devices"][0]["availability"] == "unknown"
        assert snapshot["rooms"][0]["measurements"]["temperature_c"]["quality"] == "stale"
        assert store.alerts_since() == []
        assert sent == []
        _sample(core, 2, 34)
        assert core.snapshot()["rooms"][0]["measurements"]["temperature_c"]["quality"] == "fresh"
        assert len(store.alerts_since()) == 1
    finally:
        store.close()


def test_live_copy_of_retained_sample_becomes_fresh(tmp_path, monkeypatch):
    core, store, _sent, _clock = _fixture(tmp_path, monkeypatch)
    try:
        _sample(core, 1, 32.55, retained=True)
        _sample(core, 1, 32.55)
        reading = core.snapshot()["rooms"][0]["measurements"]["temperature_c"]
        assert reading["value"] == 32.55
        assert reading["quality"] == "fresh"
    finally:
        store.close()


def test_on_for_one_hour_returns_deadline_and_turns_off(tmp_path, monkeypatch):
    core, store, sent, clock = _fixture(tmp_path, monkeypatch, commands=True)
    try:
        result = core.command("bedroom", "on", timer_minutes=60)
        assert datetime.fromisoformat(result["run_until"]) == clock[0] + timedelta(hours=1)
        clock[0] += timedelta(minutes=59, seconds=59)
        core.tick()
        assert len(sent) == 1
        clock[0] += timedelta(seconds=1)
        _sample(core, 1, 25)
        core.tick()
        assert len(sent) == 2
        assert b'"power":"off"' in sent[-1][1]
        assert core.snapshot()["rooms"][0]["automation"]["run_until"] is None
    finally:
        store.close()


def test_auto_on_after_twenty_minutes_then_off_and_cooldown(tmp_path, monkeypatch):
    core, store, sent, clock = _fixture(tmp_path, monkeypatch,
                                        automation=True, commands=True)
    try:
        assert core.ingest("home/node/ac/state",
                           b'{"power":false,"temperature":28,"mode":"cool","fan":"auto"}')
        _sample(core, 1, 33)
        core.update_presence("bedroom", True)
        core.tick()
        assert not sent
        for sample in range(2, 82):
            clock[0] += timedelta(seconds=15)
            _sample(core, sample, 33)
            core.tick()
        assert not sent
        clock[0] += timedelta(seconds=1)
        core.update_presence("bedroom", True)
        core.tick()
        assert len(sent) == 1
        assert sent[0][0] == "home/node/ac/command_v2"
        assert sent[0][2:] == (1, False)
        clock[0] += timedelta(hours=1, seconds=1)
        _sample(core, 82, 33)  # node vẫn có heartbeat khi tới hạn tắt
        core.tick()
        assert len(sent) == 2
        assert b'"power":"off"' in sent[1][1]
        assert core.snapshot()["rooms"][0]["automation"]["cooldown_until"]
        core.tick()
        assert len(sent) == 2
    finally:
        store.close()


def test_five_minute_samples_need_full_window_and_fresh_presence(tmp_path, monkeypatch):
    from dataclasses import replace
    core, store, sent, clock = _fixture(tmp_path, monkeypatch, automation=True, commands=True)
    core.settings = replace(core.settings, sensor_ttl_seconds=330, auto_on_temperature_c=32.5)
    try:
        core.ingest("home/node/ac/state", b'{"power":false,"temperature":28,"mode":"cool","fan":"auto"}')
        for sample in range(1, 5):
            _sample(core, sample, 35.85)
            core.update_presence("bedroom", True)
            core.tick()
            assert not sent
            clock[0] += timedelta(minutes=5)
        # Four readings through minute 15 do not prove minute 20.
        core.update_presence("bedroom", True)
        core.tick()
        assert not sent
        # Fifth reading proves 20 minutes, but stale webcam evidence is insufficient.
        clock[0] += timedelta(seconds=11)
        _sample(core, 5, 35.85)
        core.tick()
        assert not sent
        core.update_presence("bedroom", True)
        core.tick()
        assert len(sent) == 1
        core.tick()
        assert len(sent) == 1
    finally:
        store.close()


def test_cold_sample_missing_sample_or_threshold_change_resets_window(tmp_path, monkeypatch):
    from dataclasses import replace
    core, store, sent, clock = _fixture(tmp_path, monkeypatch, automation=True, commands=True)
    core.settings = replace(core.settings, sensor_ttl_seconds=330, auto_on_temperature_c=32.5)
    try:
        _sample(core, 1, 35.85)
        clock[0] += timedelta(minutes=5)
        _sample(core, 2, 32.5)
        assert not core._hot_since
        clock[0] += timedelta(minutes=5)
        _sample(core, 3, 35.85)
        clock[0] += timedelta(minutes=10)
        _sample(core, 4, 35.85)
        assert core._hot_since["bedroom"] == clock[0]
        core.apply_controls({"IOT_AUTO_ON_TEMPERATURE_C": 34})
        assert not core._hot_since
        assert not sent
    finally:
        store.close()


def test_gateway_api_persists_rule_without_changing_existing_timers(tmp_path, monkeypatch):
    import threading
    from dataclasses import replace
    from http.server import ThreadingHTTPServer
    from features.iot import gateway as gateway_module
    from features.iot.client import IoTClient
    from utils.control_settings import ControlSettings
    core, store, sent, clock = _fixture(tmp_path, monkeypatch, commands=True)
    prefs = ControlSettings(tmp_path / "controls.json")
    monkeypatch.setattr(gateway_module, "controls", prefs)
    gateway = gateway_module.IoTGateway.__new__(gateway_module.IoTGateway)
    gateway.core, gateway.store, gateway.token = core, store, "t" * 32
    server = ThreadingHTTPServer(("127.0.0.1", 0), gateway._handler_class())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg = replace(core.settings, api_port=server.server_port)
    cfg.token_path.write_text(gateway.token)
    client = IoTClient(cfg)
    try:
        core.command("bedroom", "schedule_off", timer_minutes=30)
        before = dict(core._room_state("bedroom"))
        result = client.configure_automation(True, 33.5)
        assert result["status"] == "saved"
        assert result["policy"]["threshold_c"] == 33.5
        assert core.settings.automation_enabled is True
        assert prefs.get("IOT_AUTO_ON_TEMPERATURE_C") == 33.5
        assert core._room_state("bedroom") == before
        assert sent == []
        import pytest
        with pytest.raises(RuntimeError):
            client.configure_automation(True, 99)
        assert prefs.get("IOT_AUTO_ON_TEMPERATURE_C") == 33.5
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        store.close()


def test_manual_off_blocks_auto_on_six_hours(tmp_path, monkeypatch):
    core, store, sent, clock = _fixture(tmp_path, monkeypatch,
                                        automation=True, commands=True)
    try:
        _sample(core, 1, 34)
        core.command("bedroom", "off")
        assert len(sent) == 1
        clock[0] += timedelta(hours=5, minutes=59)
        _sample(core, 2, 34)
        core.update_presence("bedroom", True)
        core.tick()
        assert len(sent) == 1
        assert core.snapshot()["rooms"][0]["automation"]["manual_lockout_until"]
    finally:
        store.close()


def test_user_off_timer_publishes_after_thirty_minutes(tmp_path, monkeypatch):
    core, store, sent, clock = _fixture(tmp_path, monkeypatch,
                                        automation=False, commands=True)
    try:
        scheduled = core.command("bedroom", "schedule_off", timer_minutes=30)
        assert scheduled["status"] == "scheduled"
        assert sent == []
        clock[0] += timedelta(minutes=29, seconds=59)
        core.tick()
        assert sent == []
        clock[0] += timedelta(seconds=1)
        _sample(core, 1, 25)  # node heartbeat must be fresh when the command is due
        core.tick()
        assert len(sent) == 1
        assert b'"power":"off"' in sent[0][1]
        assert core.snapshot()["rooms"][0]["automation"]["run_until"] is None
    finally:
        store.close()


def test_bad_payload_and_uncorrelated_ack_are_rejected(tmp_path, monkeypatch):
    core, store, _sent, _clock = _fixture(tmp_path, monkeypatch)
    try:
        assert not core.ingest("home/node/dht20/state",
                               b'{"temperature_c":99,"humidity_percent":60,"sample":1}')
        assert not core.ingest("home/node/ac/ack",
                               b'{"request_id":"other","command_status":"ir_sent"}')
        assert not core.ingest("home/unknown/dht20/state", b"{}")
    finally:
        store.close()


def test_current_composite_command_and_result(tmp_path, monkeypatch):
    core, store, sent, _clock = _fixture(tmp_path, monkeypatch,
                                         commands=True, protocol="composite")
    try:
        _sample(core, 1, 25)
        on = core.command("bedroom", "on", temperature_c=24, mode="cool")
        assert sent[-1] == ("home/node/ac/command", b"on 24 cool", 0, False)
        assert on["status"] == "queued_for_mqtt"
        assert core.ingest("home/node/ac/result", b"ok")
        saved = store.command(on["request_id"])
        assert saved["status"] == "node_result_ok_uncorrelated"
        assert saved["response"]["physical_ac_state_verified"] is False

        economic = core.command("bedroom", "on", temperature_c=26,
                                mode="economic")
        assert sent[-1][1] == b"on 26 economic"
        assert core.ingest("home/node/ac/result", b"ok")
        assert store.command(economic["request_id"])["status"] == \
            "node_result_ok_uncorrelated"

        off = core.command("bedroom", "off")
        assert sent[-1] == ("home/node/ac/command", b"off", 0, False)
        assert core.ingest("home/node/ac/result", b"ok")
        assert store.command(off["request_id"])["status"] == \
            "node_result_ok_uncorrelated"
    finally:
        store.close()
