# akenza for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Validate](https://github.com/sevytsch/ha-akenza/actions/workflows/validate.yml/badge.svg)](https://github.com/sevytsch/ha-akenza/actions/workflows/validate.yml)

Bring your [akenza](https://akenza.io) IoT devices into Home Assistant – **live**, with no polling delay.

* **One-step setup** – paste an akenza API key, pick the workspaces (and optionally tags) you want, done.
* **Live data** – measurements arrive through the akenza WebSocket data stream within a second of the uplink.
* **Proper devices & entities** – every akenza device becomes a Home Assistant device (manufacturer, model, firmware, serial number from the device type); every data key of every topic becomes a sensor or binary sensor with the correct device class, unit and state class derived from the akenza schema (`measurementType`).
* **Diagnostics** – online state, last seen, RSSI / SNR / spreading factor, battery and a per-organization "live stream" indicator.
* **Scales** – built for organizations with hundreds of devices: background seeding, rate-limit aware REST client, targeted entity updates.
* **Works for restricted keys and private deployments** – honours workspace access scopes and supports a custom API URL.

## Installation

### HACS (recommended)

1. In HACS open **Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/sevytsch/ha-akenza` with category **Integration**.
3. Install **akenza** and restart Home Assistant.

### Manual

Copy `custom_components/akenza` into your Home Assistant `config/custom_components/` folder and restart.

## Setup

1. In akenza open **Organization settings → API keys** and create a key. It needs read access to:
   organization, workspaces, assets (devices), device types and device data. (Write scopes are never used.)
2. In Home Assistant go to **Settings → Devices & services → Add integration → akenza**.
3. Paste the API key. The integration discovers your organization and accessible workspaces.
4. Choose the workspaces (default: all) and optionally restrict to devices carrying certain tags.

One config entry corresponds to one akenza organization. Add the integration again with another key for additional organizations.

### Options

| Option | Description |
|---|---|
| Workspaces / Tags | Which devices to import. Changing this reloads the integration. |
| Only import the default topic | Skip secondary topics (lifecycle, configuration, …). Useful for very large organizations. |
| Include data keys hidden from KPIs | Create *enabled* entities for keys the device type marks `hideFromKpis` (otherwise they are created disabled). |
| Product images | Create an `image` entity per device with the device-type product picture (default on). |
| Only data keys with data | Create entities only for data keys that have delivered a value; schema-only keys appear with their first sample (default off). |
| Metadata refresh interval | How often the device list, online state and signal metrics are refreshed (default 15 min). Measurements are live regardless. |
| API URL | Advanced: base URL of a private / regional akenza deployment (default `https://api.akenza.io`). |

## Entities

For every akenza device:

| Entity | Source |
|---|---|
| One `sensor` per numeric / string data key | device-type schema, inferred schema and live data |
| One `binary_sensor` per boolean data key | same |
| `binary_sensor` **Online** | akenza online state (diagnostic) |
| `sensor` **Last seen** | newest uplink / sample timestamp (diagnostic) |
| `sensor` **RSSI / SNR / Spreading factor / Gateways** | LoRaWAN uplink metrics (diagnostic, disabled by default) |
| `sensor` **Battery** | battery level reported in uplink metrics (diagnostic) |
| `sensor` **akenza ID** | the akenza device id (diagnostic); the physical device id (e.g. DevEUI) is shown as the device's serial number |
| `image` **Product image** | product picture of the device type (diagnostic, can be disabled in the options) |
| `device_tracker` **Position** | for every topic with `latitude`/`longitude` keys (GPS trackers) |
| `event` per button key | fires `pressed` on every new sample where a button key (`button1`, `key2`, `buttonEvent`, …) is active |

Per organization a hub device exposes **Live stream** (WebSocket connected) and **Devices** (device count, with seeding progress as attributes).

Data keys on the topics `configuration`, `raw_payload`, `fuota` and `system.*` are created **disabled** by default; enable them in the entity settings if needed. Unit, device class and state class come from the akenza `measurementType` (e.g. `akenza/environment/temperature/celsius` → temperature in °C) with a fallback on the unit and the key name. Each entity exposes `topic`, `data_key`, `measurement_type` and `last_sample` as attributes.

## Downlinks

The service **`akenza.send_downlink`** queues a downlink for a device (target: the Home Assistant device):

```yaml
action: akenza.send_downlink
target:
  device_id: 1234567890abcdef1234567890abcdef
data:
  payload: {"targetTemperature": 21}   # encoded by the device type's downlink script
  port: 1
  confirmed: false
```

Use `payload_hex: "0e14"` instead of `payload` for a raw LoRaWAN downlink; MQTT devices additionally need `topic`. The API key needs downlink permission.

## Areas and custom fields

If a device has a custom field named *Room*, *Space*, *Area*, *Location*, *Zone* or *Floor*, its value is suggested as the Home Assistant area when the device is created. All custom fields and tags are available as attributes of the **akenza ID** sensor.

## How it works

* **Discovery** uses the REST API (`/v3/organizations`, `/v3/workspace-access`, `/v3/workspaces`, `/v3/assets/list`, `/v3/device-types/{id}`).
* **Seeding** runs in the background after setup: for each device the inferred schema (`/v3/devices/{id}/infer-schema`) and the latest samples are fetched so entities have a value immediately; declared topics missing from the recent-sample window are backfilled with one targeted query each. Device types and schemas are cached locally, so restarts are fast.
* **Live updates** come from `wss://api.akenza.io/v3/data-streams`. The integration subscribes to every imported device on all topics, keeps the connection alive and reconnects with exponential back-off; after a reconnect the latest values are re-fetched so nothing is missed.
* **Metadata** (new/removed devices, online state, uplink metrics) is refreshed every 15 minutes.
* The client stays below akenza's rate limit (10 requests/s, burst 25).

> The WebSocket stream requires that device data is stored in the akenza database (the default "akenza DB" output connector). Data flows without that connector only update through the metadata refresh.

## Large organizations

Hundreds of devices mean thousands of entities. Use the workspace/tag selection and the *default topic only* option to limit what is imported, and **filter your HomeKit, Google Assistant or Alexa exposure** – the HomeKit bridge for example stops at 150 accessories.

## Troubleshooting

* **"The API key was rejected or lacks permissions"** – the key is invalid or cannot read the organization. Create a new key with read scopes.
* **Entities missing for a device** – the device may never have sent data and its device type has no schema. Entities appear automatically with the first sample.
* **Live stream is off** – check that the data flow stores data in the akenza DB and that outgoing WebSocket connections (port 443) are allowed. The integration reconnects automatically.
* Enable debug logging with:

  ```yaml
  logger:
    logs:
      custom_components.akenza: debug
  ```

* Download diagnostics from the integration page (secrets are redacted) when reporting an issue.

## Development

```bash
uv venv --python 3.14 && source .venv/bin/activate
uv pip install -r requirements_test.txt
pytest
ruff check .
```

## License

MIT – see [LICENSE](LICENSE). akenza is a trademark of akenza AG; this is a community integration.
