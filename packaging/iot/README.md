# Alice IoT deployment

The broker and gateway run from this project on Alice's Windows computer.
The LAN broker address is `192.168.2.19:1883`; the gateway's local API binds
only to `127.0.0.1:18787`.

## Current state of the device contract

The supplied ESP32 contract provides retained availability and DHT20 state.
The gateway reads those topics today. Sensor data marked retained is shown as
stale until a live sample arrives. The current composite command supplied by
the user is `on 24 cool` on `ac/command`; `off` turns it off, and `economic`
is the other supported mode. Manual commands use this protocol by default.
The node returns `ok` or an error on `ac/result`. Since this result has no
request ID, Alice permits only one outstanding command per node and labels a
matching response `node_result_ok_uncorrelated`. It does not prove the
physical A/C changed state. `IOT_AUTOMATION_ENABLED` stays false by default
until the complete path has been checked with the hardware.
Manual voice/UI commands are published while MQTT is connected even when the
node has no fresh heartbeat. They use QoS 0 without retain, so a disconnected
node will miss the command; Alice reports its availability and waits for
`ac/result` rather than claiming the A/C changed state. Automatic commands
still require a fresh online signal.
An A/C off timer is stored by the IoT gateway, separate from ordinary
reminders. Changing the A/C temperature without specifying a new timer keeps
the existing off deadline. A new timer replaces it; a manual off cancels it
after the MQTT publish is accepted. The room status tool reports the timer in
local time and distinguishes scheduled, overdue, and absent timers.

## Start from Alice

Run these one-time setup commands from the project root in PowerShell:

```powershell
.\packaging\iot\install-portable.ps1
.\packaging\iot\setup-broker.ps1
```

After setup, double-click `launch_assistant.vbs`. It starts the broker and
gateway in the background before Alice, and reuses them when they are already
running. No VS Code or terminal is needed for normal startup. If IoT startup
fails, Alice still opens and shows where to find
`packaging/iot/runtime/logs/startup.log`. Broker and gateway output is in the
same log directory. The broker and gateway continue running after the Alice
window closes.

For manual diagnostics, the foreground scripts remain available. Run the
broker and gateway scripts in separate terminals because each stays active:

```powershell
.\packaging\iot\start-broker.ps1
.\packaging\iot\test-broker.ps1
.\packaging\iot\start-gateway.ps1
```

`install-portable.ps1` downloads pinned official Mosquitto 2.1.2 and 7-Zip
files, verifies SHA-256, and extracts the broker into `packaging/iot/mosquitto/`.
It does not run either installer or register a Windows service. The binary,
downloads, data, log and credentials are ignored by Git. The source downloads
are the [Mosquitto official download](https://mosquitto.org/download/) and
[7-Zip official download](https://www.7-zip.org/download.html).

`setup-broker.ps1` creates a hashed Mosquitto password file, an ACL, and
`runtime/mosquitto.conf`. It creates separate random credentials for Alice and
ESP32, then writes only the IoT connection keys to the existing `src/.env`.
It preserves all unrelated Alice settings. The ESP32 username/password are in
`packaging/iot/runtime/credentials.json`; keep this file private. Running setup
again keeps credentials unless `-ResetCredentials` is explicitly supplied.
When started by the launcher, broker output is recorded in
`runtime/logs/broker.stderr.log`.
The node's MQTT host must be set to `192.168.2.19` and the node's username and
password must match that file.

The Alice gateway requires `paho-mqtt`. This workspace has a project-local copy
in `packaging/iot/python-deps/`; on another machine install it with the Python
configured in `launch_assistant.vbs`:

```powershell
& '<Alice Python path>' -m pip install --target packaging/iot/python-deps paho-mqtt==2.1.0
```

`start-gateway.ps1` uses Alice's configured Python and the project-local Paho.
It generates the API token in `data/iot_api_token`, stores data in `data/iot.db`,
and continues ingesting MQTT while the desktop app is closed. Webcam presence
and voice alerts require the interactive Alice app and `opencv-python` for CV.

The broker listens only on the current Alice Wi-Fi IP `192.168.2.19`. If DHCP
changes it, rerun setup with `-BindAddress <new IP>` and update ESP32's host.
Permit inbound TCP 1883 from the trusted LAN in Windows Firewall before
connecting ESP32. `test-broker.ps1` verifies authenticated publish/subscribe
on a harmless healthcheck topic; it does not send an A/C command.
For the current subnet, run `.\packaging\iot\open-firewall.ps1` once in an
elevated PowerShell terminal. It restricts the rule to this broker executable,
`192.168.2.19:1883`, and clients in `192.168.2.0/24`.

To watch real device data from the project root, use the gateway client options:

```powershell
.\packaging\iot\mosquitto\mosquitto_sub.exe -o .\packaging\iot\runtime\gateway-client.opts -t 'home/esp32s3-ir-gateway/#' -v
```

MQTT Explorer can use the `gateway_username` and `gateway_password` in
`runtime/credentials.json`. Its subscription to
`home/esp32s3-ir-gateway/#` can now display `ac/command` as well as sensor
and result topics. Use a client ID different from `alice-iot-gateway`.

To publish an actual A/C command after checking the node is connected and IR
hardware is ready, use `mosquitto_pub.exe` with the same options and
`-t 'home/esp32s3-ir-gateway/ac/command' -m 'on 24 cool'` (or `-m 'off'`).
This direct CLI path bypasses Alice's command log and timers; normal voice
control should go through the Alice gateway.

After hardware validation, the gateway can optionally be installed as a
Windows Service from an elevated terminal; see `src/features/iot/windows_service.py`.
The service environment must include Paho and access to `src/.env` and `data/`.

## Multi-room mapping

Copy `devices.example.json` to `data/iot_devices.json` to customize rooms and
devices. Every MQTT node needs a unique `device_id` and `topic_prefix`. The
current gateway topic remains `home/esp32s3-ir-gateway/...`; mapping it to
`bedroom` is configuration, not a topic change. Optional lux ingestion uses
`<topic_prefix>/light/state` with JSON `{"illuminance_lux": 123}` when a node
implements it. No light control is provided.
Add a second device object with `room_id: "living_room"` and its own
`device_id`/`topic_prefix` when that node exists. Room IDs must be unique
across homes because voice commands currently address a room by its ID.

## Current A/C command contract

Alice publishes non-retained text at QoS 0 to
`<topic_prefix>/ac/command`. Examples: `on 24 cool`, `on 26 economic`, and
`off`. If a voice request says only "bật máy lạnh", the default is `on 28 cool`.
The broker host is `192.168.2.19`; `192.168.1.10` in the user's example is
treated as an old sample address. The gateway listens for non-retained
`ac/result = ok` or an error. A command that gets no response within ten
seconds is `ack_timeout_unknown`; this is not proof the node did nothing.
`queued_for_mqtt` only means the local MQTT client accepted the publish call;
the `ok` result is the first node-side signal Alice can observe.

## Future correlated acknowledgement

Alice publishes non-retained QoS 1 JSON to
`<topic_prefix>/ac/command_v2`:

```json
{"request_id":"uuid","power":"on","expires_at":"2026-09-25T01:00:30+00:00"}
```

The node should send an application acknowledgement to
`<topic_prefix>/ac/ack` containing the same `request_id`,
`command_status` (`received`, `ir_sent`, or `failed`), and structured
`reported_state` (model, power, mode, temperature, fan). `ir_sent` means that
the node received this command and attempted IR transmission. The current
firmware's text `ac/result` cannot support this correlation. The node must
deduplicate `request_id` because MQTT QoS 1 can deliver a command more than
once. Its clock must be synchronized if it enforces `expires_at`.

The gateway retains an optional `IOT_COMMAND_PROTOCOL=v2` path for a future
node firmware with request IDs. Enable `IOT_AUTOMATION_ENABLED=true` only
after checking camera coverage, temperature freshness, room mapping, A/C IR
behavior, and timed off behavior on the actual hardware. Auto-on requires
the configured threshold (default 32.5 °C) for 20 minutes, proven by live samples
every five minutes, plus fresh
presence in that room; it runs for one hour, then sends off. The two-hour
cooldown follows automatic/timer off. A spoken off command blocks auto-on for
six hours. Raw samples are retained seven days and hourly summaries fourteen
days. The history API returns hourly summaries for up to fourteen days.
Temperature freshness defaults to 330 seconds; webcam presence remains 10 seconds.
The main HUD control panel persists IoT switches and the threshold without editing
`.env`; the gateway reloads these controls every second. Restart an older gateway
once after installing this version. See `docs/system_control_panel.md`.
Room IDs are unique across homes in the current API; this avoids ambiguous
voice commands such as "bedroom" when more rooms are configured.
