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
SEED_CONCURRENCY: Final = 4
SEED_NOTIFY_EVERY: Final = 25

# WebSocket stream
WS_PATH: Final = "/v3/data-streams"
WS_HEARTBEAT: Final = 25
WS_RECEIVE_TIMEOUT: Final = 90
WS_GREETING_TIMEOUT: Final = 15
WS_SUBSCRIBE_CHUNK: Final = 100
WS_BACKOFF_MAX: Final = 300
RESEED_DEBOUNCE: Final = 30

# Topics whose data keys are considered diagnostic
DIAGNOSTIC_TOPICS: Final = frozenset({"lifecycle", "configuration", "raw_payload", "fuota"})
# Topics whose entities are disabled by default
DISABLED_TOPICS: Final = frozenset({"configuration", "raw_payload", "fuota"})
DIAGNOSTIC_TOPIC_PREFIXES: Final = ("system", "network", "debug", "diagnostic")
DEFAULT_TOPIC: Final = "default"

STORAGE_VERSION: Final = 1
