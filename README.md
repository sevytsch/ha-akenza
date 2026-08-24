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
   The key may be limited to individual workspaces – only those workspaces are offered during setup.
2. In Home Assistant go to **Settings → Devices & services → Add integration → akenza**.
3. Paste the API key. The integration discovers your organization and accessible workspaces.
4. Choose the workspaces (default: all) and optionally restrict to devices carrying certain tags.
5. **Import everything** (recommended) – or pick *Select data points per device type* to deselect data points / topics per device type before anything is created. Both can be changed later in the options.

One config entry corresponds to one akenza organization. Add the integration again with another key for additional organizations.

### Options

| Option | Description |
|---|---|
| Workspaces / Tags | Which devices to import. Selecting every workspace means "all", so workspaces created later are included automatically. Devices added to akenza later (or tagged later) are picked up by the next metadata refresh and seeded right away. Changing this reloads the integration. |
| Data points per device type | Second menu entry of the options dialog: pick a device type (or a device without one) and deselect the data points or whole topics (`topic · *`) you do not want. Applies to all devices of that type; deselected entities are removed, data points that appear later stay enabled. |
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

## Energy dashboard

Meter readings are created as long-term-statistics sensors that the Home Assistant **Energy dashboard** accepts directly:

| akenza data point | Home Assistant |
|---|---|
| `activeEnergy` (Wh, kWh, MWh), any key with an energy unit (`Wh`…`GWh`, `J`…`GJ`) | `device_class: energy`, `state_class: total_increasing` |
| `reactiveEnergy` (varh, kvarh) | `reactive_energy`, `total_increasing` |
| volume in `m³` / `L` / `gal` with `water` in the key | `water`, `total_increasing` |
| volume with `gas` in the key | `gas`, `total_increasing` |
| other volumes (e.g. heat-meter `volume`) | `volume`, `total_increasing` |
| `m³/h`, `L/min`, … | `volume_flow_rate` |

Add the `…Cumulative` / total sensors (grid consumption, return, gas, water) under *Settings → Dashboards → Energy*. Values that only hold the **consumption of the last interval** – `activeEnergyPositive` next to `activeEnergyPositiveCumulative`, `consumption` next to `consumptionCumulative`, `periodicCounterIn`, `daily…`, `relative…` – are deliberately created **without** an energy device class (unit kept, `state_class: measurement`) so they cannot corrupt the dashboard. Use the cumulative sibling instead.

## Control entities (downlink scripts)

For LoRaWAN device types that ship a **downlink encoder script**, the integration reads which payload fields the script understands and creates control entities automatically:

| Script fields | Entity | Notes |
|---|---|---|
| `red`, `green`, `blue` (+ `onDuration`/`offDuration`) | `light` with RGB colour, brightness and effects *solid / blink_slow / blink_fast* | e.g. Plenom Kuando Busylight. The Busylight reports its colour back (`lastColorRGB`), so the state stops being assumed once the device confirms. As a class C device it applies the colour within seconds. |
| `setTargetTemperature` | `number` *Target temperature* (5–30 °C) | MClimate Vicki. Shows the reported `targetTemperature` once the valve confirms. |
| `setChildLock` | `switch` *Child lock* | MClimate Vicki, follows the reported `childLock`. |

Entities appear only when the device type's script really references the field – a device type with a pass-through script gets none. Downlinks are queued at akenza; class C devices (mains powered, e.g. the Busylight) receive them within seconds, class A devices (battery powered, e.g. Vicki) with their next uplink. A confirmed downlink that the device fails to acknowledge is retried by the network server and blocks the queue until it succeeds. For anything else use the service below.

## Downlinks

The service **`akenza.send_downlink`** queues a downlink for a device (`device_id` is the Home Assistant device):

```yaml
action: akenza.send_downlink
data:
  device_id: 1234567890abcdef1234567890abcdef
  payload: {"targetTemperature": 21}   # encoded by the device type's downlink script
  port: 1
  confirmed: false
```

Use `payload_hex: "0e14"` instead of `payload` for a raw LoRaWAN downlink; MQTT devices additionally need `topic`. The API key needs downlink permission.

## Events and the hub device

Every organization has a hub device with *Live stream* (connectivity), *Devices* (count, with seeding progress as attributes) and the button **Scan for new devices**, which refreshes the device list right away instead of waiting for the next metadata refresh. New devices are seeded immediately.

Two events are fired for automations:

```yaml
triggers:
  - trigger: event
    event_type: akenza_device_added      # or akenza_device_removed
actions:
  - action: notify.mobile_app_phone
    data:
      message: "New akenza device: {{ trigger.event.data.name }} ({{ trigger.event.data.device_type }})"
```

Event data: `akenza_id`, `name`, `workspace_id`, `organization_id`, `device_type`, `tags`, `config_entry_id`.

## Repairs

Problems that would otherwise degrade silently are shown under **Settings → System → Repairs**:

* **API key lacks permissions** – the key cannot read device types, infer schemas or device data. Devices are still imported; create a key with the read scopes listed under *Setup* and use *Reconfigure*.
* **Selected workspace unavailable** – a selected workspace was deleted or the key lost access; its devices are removed, the others keep working. Adjust the selection in the options.
* **Live stream disconnected** – the WebSocket has been down for more than 10 minutes (reconnects automatically).

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
