# Changelog

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
