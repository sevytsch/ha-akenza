# Changelog

## 0.4.0 - 2026-08-24

### Added
- **Data points per device type**: the initial setup offers "Import everything" (default) or restricting data points per device type right away (from the device-type schemas); the options menu has a new step where, per device type (or per device without a device type), individual data points or whole topics can be deselected. Everything is selected by default; deselected data points get no entities (existing ones are removed on reload), data points that appear later stay enabled.
- Devices that appear in akenza after setup (new device, new tag) are now seeded immediately when the metadata poll finds them, instead of showing `unknown` until their next uplink.

- **Energy dashboard ready**: meter readings are mapped to `energy` / `reactive_energy` / `water` / `gas` / `volume` with `total_increasing` (incl. `MWh`, `GJ`, `varh`, `m³`, `L`, flow rates), also for custom device types (`measurementType: custom`, unit only). Interval values next to a cumulative sibling (`activeEnergyPositive` vs `…Cumulative`, `consumption` vs `consumptionCumulative`, `periodicCounterIn` vs `totalCounterIn`, `relative…`, `daily…`) are no longer treated as meter readings. Power factor gets its device class.

- **Control entities from downlink scripts**: if a LoRaWAN device type has a downlink encoder, the integration reads the payload fields it understands and creates matching entities – an RGB **light** (with brightness and solid/blink effects) when the script takes `red`/`green`/`blue` (e.g. Kuando Busylight), a **number** *Target temperature* for `setTargetTemperature` and a **switch** *Child lock* for `setChildLock` (MClimate Vicki). Numbers/switches show the value the device reports back and are marked as assumed until then; the light adopts the colour the Busylight reports back (`lastColorRGB`). Everything else stays available via `akenza.send_downlink`.
- **Hub button "Scan for new devices"** refreshes the device list immediately; **events** `akenza_device_added` / `akenza_device_removed` (with `akenza_id`, `name`, `workspace_id`, `device_type`, `tags`) for automations.
- **Repair issues** instead of silent degradation: API key lacking permissions (device types, infer-schema, device data), selected workspaces that no longer exist or are no longer accessible (their devices are removed, the remaining workspaces keep working), and a live stream disconnected for more than 10 minutes.

### Changed
- Selecting every accessible workspace now stores "all workspaces", so workspaces created later are included automatically.
- The options dialog is now a menu (workspaces/tags/behaviour vs. data points).

## 0.3.1 - 2026-08-22

### Fixed
- Setup failed with "Permission denied: no role exists matching the criteria" for API keys scoped to individual workspaces. The device listing no longer sends `organizationId` alongside `workspaceIds`, which triggered an organization-level permission check that workspace-scoped keys cannot pass.
- `akenza.send_downlink` now takes the device as a `device_id` field (device selector) instead of a service target, as required by current hassfest.

## 0.3.0 – 2026-08-20

* **Device tracker** entities for topics that carry `latitude`/`longitude` (GPS trackers).
* **Event** entities (`pressed`) for button data keys (e.g. `button1`, `key2`, `buttonEvent`), in addition to the existing sensors.
* **Service `akenza.send_downlink`**: queue LoRaWAN or MQTT downlinks (JSON payload for the device type's encoder, or raw hex).
* Option **Only data keys with data**: skip schema-only keys until they deliver a value.
* Custom fields are read; a field named Room / Space / Area / Location / Zone / Floor becomes the suggested area, all custom fields and tags are attributes of the *akenza ID* sensor.

## 0.2.5 – 2026-08-20

* Also cap restored string values at 255 characters (errors during startup).

## 0.2.4 – 2026-08-20

* Clear the device-type id that versions before 0.2.2 stored as `model_id` in the device registry.

## 0.2.3 – 2026-08-20

* String values longer than 255 characters are truncated for the state (full value in the `full_value` attribute) instead of being rejected by Home Assistant.

## 0.2.2 – 2026-08-20

* Device info no longer shows the device-type id as model id.
* New diagnostic sensor **akenza ID** per device (the physical device id is shown as serial number).
* README: note on filtering HomeKit/Google/Alexa exposure for large organizations.

## 0.2.1 – 2026-08-20

* Seeding backfills topics that the recent-sample window missed (devices with several topics), using `/query/topics` plus one targeted query per topic.
* Seeding concurrency raised to 6.

## 0.2.0 – 2026-08-20

* New `image` entity per device showing the product picture of its device type (option *Product images*, on by default).

## 0.1.1 – 2026-08-20

* Devices link directly to their page in the akenza portal.
* Icons for data points without a device class.
* Hub device is created before platforms (fixes `via_device` warning).
* WebSocket stream closes quietly on Home Assistant shutdown.

## 0.1.0 – 2026-08-20

* Initial release: config flow with workspace/tag selection, live WebSocket updates, schema-based sensors and binary sensors, diagnostics, reauth/reconfigure/options flows, English and German translations.
