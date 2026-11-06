"""Constants for the akenza integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "akenza"

CONF_BASE_URL: Final = "base_url"
CONF_ORGANIZATION_ID: Final = "organization_id"
CONF_ORGANIZATION_NAME: Final = "organization_name"
CONF_WORKSPACE_IDS: Final = "workspace_ids"
CONF_TAG_IDS: Final = "tag_ids"
CONF_DEFAULT_TOPIC_ONLY: Final = "default_topic_only"
CONF_ENABLE_HIDDEN_KPIS: Final = "enable_hidden_kpis"
CONF_POLL_INTERVAL: Final = "poll_interval_minutes"
CONF_DEVICE_IMAGES: Final = "device_images"
CONF_DATA_KEYS_ONLY: Final = "data_keys_only"
# {device_type_id | "device:<akenza_id>": ["topic/key", "topic/*", ...]}
CONF_EXCLUDED_DATA_POINTS: Final = "excluded_data_points"
DEVICE_TARGET_PREFIX: Final = "device:"
TOPIC_WILDCARD: Final = "*"

DEFAULT_BASE_URL: Final = "https://api.akenza.io"
DEFAULT_POLL_INTERVAL: Final = 15
MIN_POLL_INTERVAL: Final = 5
MAX_POLL_INTERVAL: Final = 1440

PORTAL_URL: Final = "https://app.akenza.io"
PORTAL_ORG_URL_TEMPLATE: Final = PORTAL_URL + "/org/{organization_id}/overview"
PORTAL_DEVICE_URL_TEMPLATE: Final = (
    PORTAL_URL + "/org/{organization_id}/ws/{workspace_id}/assets/device/{device_id}"
)

# REST client
API_TIMEOUT: Final = 30
PAGE_SIZE: Final = 100
RATE_LIMIT_RATE: Final = 8.0
RATE_LIMIT_BURST: Final = 20
SEED_SAMPLE_LIMIT: Final = 25
SEED_CONCURRENCY: Final = 6
SEED_NOTIFY_EVERY: Final = 25

# WebSocket stream
WS_PATH: Final = "/v3/data-streams"
WS_HEARTBEAT: Final = 25
WS_RECEIVE_TIMEOUT: Final = 90
WS_GREETING_TIMEOUT: Final = 15
WS_SUBSCRIBE_CHUNK: Final = 100
WS_BACKOFF_MAX: Final = 300
RESEED_DEBOUNCE: Final = 30
# outages shorter than this skip the full reseed (daily server-side recycling)
RESEED_MIN_OUTAGE: Final = 60

# Topics whose data keys are considered diagnostic
DIAGNOSTIC_TOPICS: Final = frozenset({"lifecycle", "configuration", "raw_payload", "fuota"})
# Topics whose entities are disabled by default
DISABLED_TOPICS: Final = frozenset({"configuration", "raw_payload", "fuota"})
DIAGNOSTIC_TOPIC_PREFIXES: Final = ("system", "network", "debug", "diagnostic")
DEFAULT_TOPIC: Final = "default"
MAX_BACKFILL_TOPICS: Final = 10

STORAGE_VERSION: Final = 1

# custom field names (lower-case) that are used as area suggestion
AREA_FIELD_NAMES: Final = frozenset({"room", "space", "area", "location", "zone", "raum", "floor"})
# data keys that form a GPS position
LATITUDE_KEYS: Final = ("latitude", "lat")
LONGITUDE_KEYS: Final = ("longitude", "lng", "lon", "long")
GPS_ACCURACY_KEYS: Final = ("accuracy", "gpsAccuracy", "hdop")

SERVICE_SEND_DOWNLINK: Final = "send_downlink"
EVENT_DEVICE_ADDED: Final = "akenza_device_added"
EVENT_DEVICE_REMOVED: Final = "akenza_device_removed"
# repair issues
ISSUE_MISSING_PERMISSIONS: Final = "missing_permissions"
ISSUE_WORKSPACE_UNAVAILABLE: Final = "workspace_unavailable"
ISSUE_STREAM_DISCONNECTED: Final = "stream_disconnected"
STREAM_ISSUE_DELAY: Final = 600
README_URL: Final = "https://github.com/sevytsch/ha-akenza#readme"
ATTR_PAYLOAD: Final = "payload"
ATTR_PAYLOAD_HEX: Final = "payload_hex"
ATTR_PORT: Final = "port"
ATTR_CONFIRMED: Final = "confirmed"
ATTR_TOPIC: Final = "topic"
EVENT_TYPE_PRESSED: Final = "pressed"
