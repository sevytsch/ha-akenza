"""Coordinator: metadata polling, background seeding and live WebSocket push."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable, Coroutine, Iterable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AkenzaApiClient,
    AkenzaAuthError,
    AkenzaConnectionError,
    AkenzaForbiddenError,
    AkenzaNotFoundError,
)
from .const import (
    CONF_DATA_KEYS_ONLY,
    CONF_DEFAULT_TOPIC_ONLY,
    CONF_DEVICE_IMAGES,
    CONF_ENABLE_HIDDEN_KPIS,
    CONF_EXCLUDED_DATA_POINTS,
    CONF_ORGANIZATION_ID,
    CONF_ORGANIZATION_NAME,
    CONF_POLL_INTERVAL,
    CONF_TAG_IDS,
    CONF_WORKSPACE_IDS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TOPIC,
    DEVICE_TARGET_PREFIX,
    DIAGNOSTIC_TOPIC_PREFIXES,
    DISABLED_TOPICS,
    DOMAIN,
    EVENT_DEVICE_ADDED,
    EVENT_DEVICE_REMOVED,
    ISSUE_MISSING_PERMISSIONS,
    ISSUE_STREAM_DISCONNECTED,
    ISSUE_WORKSPACE_UNAVAILABLE,
    MAX_BACKFILL_TOPICS,
    README_URL,
    RESEED_DEBOUNCE,
    RESEED_MIN_OUTAGE,
    SEED_CONCURRENCY,
    SEED_NOTIFY_EVERY,
    SEED_SAMPLE_LIMIT,
    STREAM_ISSUE_DELAY,
    TOPIC_WILDCARD,
)
from .models import AkenzaDevice, AkenzaDeviceType, DataPointDescriptor, DeviceState, Sample
from .schema import (
    descriptors_from_schemas,
    flatten_sample_data,
    infer_descriptor,
    merge_descriptors,
)
from .storage import AkenzaCache
from .stream import AkenzaStream

_LOGGER = logging.getLogger(__name__)

HUB_KEY = "__hub__"

type AkenzaConfigEntry = ConfigEntry[AkenzaCoordinator]


class AkenzaCoordinator(DataUpdateCoordinator[dict[str, DeviceState]]):
    """Holds all device states for one akenza organization (one config entry)."""

    config_entry: AkenzaConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: AkenzaConfigEntry, client: AkenzaApiClient
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(hass, _LOGGER, config_entry=entry, name=DOMAIN, update_interval=None)
        self.client = client
        self.cache = AkenzaCache(hass, entry.entry_id)
        self.organization_id: str = entry.data[CONF_ORGANIZATION_ID]
        self.organization_name: str = entry.data.get(CONF_ORGANIZATION_NAME) or self.organization_id
        self.workspace_ids: list[str] = list(entry.options.get(CONF_WORKSPACE_IDS) or [])
        self.tag_ids: set[str] = set(entry.options.get(CONF_TAG_IDS) or [])
        self.default_topic_only: bool = bool(entry.options.get(CONF_DEFAULT_TOPIC_ONLY, False))
        self.enable_hidden_kpis: bool = bool(entry.options.get(CONF_ENABLE_HIDDEN_KPIS, False))
        self.device_images: bool = bool(entry.options.get(CONF_DEVICE_IMAGES, True))
        self.data_keys_only: bool = bool(entry.options.get(CONF_DATA_KEYS_ONLY, False))
        self.excluded: dict[str, frozenset[str]] = {
            str(target): frozenset(str(v) for v in values)
            for target, values in (entry.options.get(CONF_EXCLUDED_DATA_POINTS) or {}).items()
        }
        self.poll_interval = timedelta(
            minutes=int(entry.options.get(CONF_POLL_INTERVAL) or DEFAULT_POLL_INTERVAL)
        )
        self.stream = AkenzaStream(
            async_get_clientsession(hass),
            client.websocket_url,
            client.api_key,
            on_sample=self._handle_sample,
            on_connection=self._handle_connection,
            on_auth_failed=self._handle_auth_failed,
        )
        self._access_ids: list[str] | None = None
        self._device_listeners: dict[str, set[Callable[[], None]]] = {}
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_reseed: CALLBACK_TYPE | None = None
        self._seed_task: asyncio.Task[None] | None = None
        self._connections = 0
        self._disconnected_at: float | None = None
        self._unavailable_types: set[str] = set()
        self._missing_workspaces: set[str] = set()
        self._forbidden: set[str] = set()
        self._unsub_stream_issue: CALLBACK_TYPE | None = None
        self.seeding_done = False
        self.seeded_devices = 0

    # --- lifecycle -------------------------------------------------------

    async def _async_setup(self) -> None:
        await self.cache.async_load()
        try:
            access = await self.client.async_get_workspace_access(self.organization_id)
        except AkenzaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AkenzaForbiddenError:
            self._access_ids = None
        except AkenzaConnectionError as err:
            raise UpdateFailed(str(err)) from err
        else:
            self._access_ids = None if access.all else sorted(access.ids)
        self._update_workspace_issue()

    def _effective_workspace_ids(self) -> list[str]:
        ids = [w for w in self.workspace_ids if w not in self._missing_workspaces]
        if ids or self.workspace_ids:
            if self._access_ids is None:
                return ids
            return [w for w in ids if w in self._access_ids]
        return [w for w in (self._access_ids or []) if w not in self._missing_workspaces]

    # --- repair issues ---------------------------------------------------

    def _issue_id(self, issue: str) -> str:
        return f"{issue}_{self.config_entry.entry_id}"

    def _update_workspace_issue(self) -> None:
        """Selected workspaces the key cannot see any more -> repair issue."""
        unavailable = set(self._missing_workspaces)
        if self._access_ids is not None:
            unavailable |= {w for w in self.workspace_ids if w not in self._access_ids}
        if unavailable:
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id(ISSUE_WORKSPACE_UNAVAILABLE),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_WORKSPACE_UNAVAILABLE,
                translation_placeholders={
                    "organization": self.organization_name,
                    "workspaces": ", ".join(sorted(unavailable)),
                },
                learn_more_url=README_URL,
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(ISSUE_WORKSPACE_UNAVAILABLE))

    def _note_forbidden(self, what: str) -> None:
        """Record an endpoint the API key may not call and raise/update the repair issue."""
        if what in self._forbidden:
            return
        self._forbidden.add(what)
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            self._issue_id(ISSUE_MISSING_PERMISSIONS),
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_MISSING_PERMISSIONS,
            translation_placeholders={
                "organization": self.organization_name,
                "endpoints": ", ".join(sorted(self._forbidden)),
            },
            learn_more_url=README_URL,
        )

    @callback
    def _update_stream_issue(self, connected: bool) -> None:
        """Raise a repair issue when the live stream stays disconnected for a while."""
        if self._unsub_stream_issue:
            self._unsub_stream_issue()
            self._unsub_stream_issue = None
        if connected:
            ir.async_delete_issue(self.hass, DOMAIN, self._issue_id(ISSUE_STREAM_DISCONNECTED))
            return

        @callback
        def _raise(_now: Any) -> None:
            self._unsub_stream_issue = None
            if self.stream.connected:
                return
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                self._issue_id(ISSUE_STREAM_DISCONNECTED),
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_STREAM_DISCONNECTED,
                translation_placeholders={
                    "organization": self.organization_name,
                    "status_url": "https://status.akenza.io",
                },
                learn_more_url=README_URL,
            )

        self._unsub_stream_issue = async_call_later(self.hass, STREAM_ISSUE_DELAY, _raise)

    async def _async_list_devices(self) -> list[AkenzaDevice]:
        """List devices; drop workspaces that akenza reports as gone (repair issue)."""
        for _ in range(len(self.workspace_ids) + 1):
            effective = self._effective_workspace_ids()
            if not effective and (self.workspace_ids or self._access_ids is not None):
                # every selected (or accessible) workspace is gone; an empty list
                # would fall back to the organization-wide listing
                return []
            try:
                return await self.client.async_list_devices(self.organization_id, effective)
            except AkenzaNotFoundError as err:
                match = re.search(r"workspace with id (\w+) not found", str(err), re.IGNORECASE)
                if not match or match.group(1) in self._missing_workspaces:
                    raise UpdateFailed(str(err)) from err
                _LOGGER.warning("Workspace %s no longer exists, skipping it", match.group(1))
                self._missing_workspaces.add(match.group(1))
                self._update_workspace_issue()
                if not self._effective_workspace_ids() and self.workspace_ids:
                    return []
        raise UpdateFailed("No accessible workspace left")

    async def _async_update_data(self) -> dict[str, DeviceState]:
        """Metadata refresh: device list, device types, online state."""
        try:
            devices = await self._async_list_devices()
        except (AkenzaAuthError, AkenzaForbiddenError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except AkenzaConnectionError as err:
            raise UpdateFailed(str(err)) from err

        if self.tag_ids:
            devices = [d for d in devices if d.tag_ids & self.tag_ids]

        await self._async_fetch_device_types(
            {d.device_type_id for d in devices if d.device_type_id}
        )

        previous = self.data or {}
        states: dict[str, DeviceState] = {}
        for device in devices:
            state = previous.get(device.id)
            device_type = (
                self.cache.device_types.get(device.device_type_id)
                if device.device_type_id
                else None
            )
            if state is None:
                state = DeviceState(device=device, device_type=device_type)
                state.descriptors = merge_descriptors(
                    self._type_descriptors(device_type),
                    self.cache.descriptors.get(device.id, {}),
                )
            else:
                state.device = device
                if state.device_type is None and device_type is not None:
                    state.device_type = device_type
                    state.descriptors = merge_descriptors(
                        self._type_descriptors(device_type), state.descriptors
                    )
            if device.uplink_metrics and device.uplink_metrics.timestamp:
                ts = device.uplink_metrics.timestamp
                if state.last_seen is None or ts > state.last_seen:
                    state.last_seen = ts
            states[device.id] = state

        removed = set(previous) - set(states)
        if removed:
            for device_id in sorted(removed):
                self._fire_device_event(EVENT_DEVICE_REMOVED, previous[device_id].device)
            self._remove_devices(removed)
        self.stream.set_asset_ids(states.keys(), self._create_task)
        if self.data is not None and (added := set(states) - set(previous)):
            _LOGGER.debug("%d new device(s) found, seeding", len(added))
            for device_id in sorted(added):
                self._fire_device_event(EVENT_DEVICE_ADDED, states[device_id].device)
            # not eager: the seeding must see the new states once they are published
            self.config_entry.async_create_background_task(
                self.hass,
                self._async_seed(infer=True, device_ids=sorted(added)),
                f"{DOMAIN}_seed_new",
                eager_start=False,
            )
        return states

    @callback
    def _fire_device_event(self, event_type: str, device: AkenzaDevice) -> None:
        self.hass.bus.async_fire(
            event_type,
            {
                "config_entry_id": self.config_entry.entry_id,
                "organization_id": self.organization_id,
                "workspace_id": device.workspace_id,
                "akenza_id": device.id,
                "name": device.name,
                "device_type": device.device_type_name,
                "tags": list(device.tag_names),
            },
        )

    def _type_descriptors(
        self, device_type: AkenzaDeviceType | None
    ) -> dict[str, DataPointDescriptor]:
        if device_type is None:
            return {}
        return descriptors_from_schemas(device_type.schemas)

    async def _async_fetch_device_types(self, type_ids: Iterable[str]) -> None:
        missing = [
            t
            for t in set(type_ids)
            if t not in self.cache.device_types and t not in self._unavailable_types
        ]
        if not missing:
            return

        async def fetch(type_id: str) -> None:
            try:
                self.cache.device_types[type_id] = await self.client.async_get_device_type(type_id)
            except AkenzaAuthError:
                raise
            except AkenzaForbiddenError as err:
                _LOGGER.debug("Device type %s not accessible: %s", type_id, err)
                self._unavailable_types.add(type_id)
                self._note_forbidden("device-types")
            except AkenzaNotFoundError as err:
                _LOGGER.debug("Device type %s not found: %s", type_id, err)
                self._unavailable_types.add(type_id)
            except AkenzaConnectionError as err:
                _LOGGER.debug("Device type %s could not be fetched: %s", type_id, err)

        try:
            await asyncio.gather(*(fetch(t) for t in missing))
        except AkenzaAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        self.cache.async_schedule_save()

    def _remove_devices(self, device_ids: set[str]) -> None:
        registry = dr.async_get(self.hass)
        for device_id in device_ids:
            self.cache.descriptors.pop(device_id, None)
            self._device_listeners.pop(device_id, None)
            entry = registry.async_get_device_by_identifier(
                (DOMAIN, device_id), self.config_entry.entry_id
            )
            if entry is not None:
                registry.async_update_device(
                    entry.id, remove_config_entry_id=self.config_entry.entry_id
                )

    @callback
    def async_start(self) -> None:
        """Start stream, seeding and the metadata poll timer (after first refresh)."""
        self.stream.set_asset_ids(self.data.keys(), self._create_task)
        self.stream.start(self._create_task)
        self._seed_task = self._create_task(self._async_seed(infer=True))
        self._unsub_timer = async_track_time_interval(
            self.hass, self._async_poll, self.poll_interval
        )

    async def _async_poll(self, _now: Any) -> None:
        await self.async_refresh()

    async def async_shutdown(self) -> None:
        """Stop background work."""
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        if self._unsub_reseed:
            self._unsub_reseed()
            self._unsub_reseed = None
        if self._unsub_stream_issue:
            self._unsub_stream_issue()
            self._unsub_stream_issue = None
        if self._seed_task and not self._seed_task.done():
            self._seed_task.cancel()
        await self.stream.async_stop()
        await super().async_shutdown()

    def _create_task(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        return self.config_entry.async_create_background_task(self.hass, coro, f"{DOMAIN}_task")

    # --- seeding ---------------------------------------------------------

    async def _async_seed(self, *, infer: bool, device_ids: Iterable[str] | None = None) -> None:
        """Fetch schemas and latest values for devices in the background."""
        ids = list(device_ids) if device_ids is not None else list(self.data or {})
        # online devices first so the common case is ready quickly
        ids.sort(key=lambda i: 0 if (self.data.get(i) and self.data[i].device.online) else 1)
        semaphore = asyncio.Semaphore(SEED_CONCURRENCY)
        done = 0
        touched: set[str] = set()

        async def seed_one(device_id: str) -> None:
            nonlocal done
            async with semaphore:
                if await self._async_seed_device(device_id, infer=infer):
                    touched.add(device_id)
                done += 1
                if done % SEED_NOTIFY_EVERY == 0:
                    self._flush_seeded(touched)

        try:
            await asyncio.gather(*(seed_one(i) for i in ids))
        except AkenzaAuthError:
            self._handle_auth_failed()
            return
        finally:
            self._flush_seeded(touched)
            self.cache.async_schedule_save()
        if device_ids is None:
            self.seeding_done = True
            self.async_update_listeners()

    def _flush_seeded(self, touched: set[str]) -> None:
        self.async_update_listeners()
        for device_id in list(touched):
            self._notify(device_id)
        touched.clear()

    async def _async_seed_device(self, device_id: str, *, infer: bool) -> bool:
        state = self.data.get(device_id)
        if state is None:
            return False
        if infer:
            try:
                schema = await self.client.async_infer_schema(device_id)
            except AkenzaForbiddenError as err:
                _LOGGER.debug("infer-schema for %s failed: %s", device_id, err)
                self._note_forbidden("infer-schema")
                schema = {}
            except (AkenzaNotFoundError, AkenzaConnectionError) as err:
                _LOGGER.debug("infer-schema for %s failed: %s", device_id, err)
                schema = {}
            inferred = descriptors_from_schemas(schema, inferred=True)
            state.descriptors = merge_descriptors(
                self._type_descriptors(state.device_type), inferred, state.descriptors
            )
        try:
            samples = await self.client.async_query_latest(device_id, SEED_SAMPLE_LIMIT)
        except AkenzaForbiddenError as err:
            _LOGGER.debug("query for %s failed: %s", device_id, err)
            self._note_forbidden("device data (query)")
            samples = []
        except AkenzaConnectionError as err:
            _LOGGER.debug("query for %s failed: %s", device_id, err)
            samples = []
        seen_topics: set[str] = set()
        for sample in samples:  # newest first
            if sample.topic in seen_topics:
                continue
            seen_topics.add(sample.topic)
            self._apply_sample(sample, notify=False)
        await self._async_backfill_topics(device_id, seen_topics, had_samples=bool(samples))
        state.seeded = True
        self.seeded_devices += 1
        self.cache.descriptors[device_id] = dict(state.descriptors)
        return True

    async def _async_backfill_topics(
        self, device_id: str, seen_topics: set[str], *, had_samples: bool
    ) -> None:
        """Fetch the newest sample of declared topics the recent-sample window missed."""
        state = self.data.get(device_id)
        if state is None or not had_samples:
            return
        wanted = {
            d.topic
            for d in state.descriptors.values()
            if d.topic not in seen_topics
            and d.topic not in DISABLED_TOPICS
            and not d.topic.startswith(DIAGNOSTIC_TOPIC_PREFIXES)
            and self.topic_wanted(state, d.topic)
        }
        if not wanted:
            return
        try:
            available = set(await self.client.async_get_topics(device_id))
        except (AkenzaForbiddenError, AkenzaNotFoundError, AkenzaConnectionError) as err:
            _LOGGER.debug("topics for %s failed: %s", device_id, err)
            return
        for topic in sorted(wanted & available)[:MAX_BACKFILL_TOPICS]:
            try:
                sample = await self.client.async_query_topic_latest(device_id, topic)
            except (AkenzaForbiddenError, AkenzaConnectionError) as err:
                _LOGGER.debug("backfill %s/%s failed: %s", device_id, topic, err)
                continue
            if sample is not None:
                self._apply_sample(sample, notify=False)

    # --- live push -------------------------------------------------------

    @callback
    def _handle_sample(self, sample: Sample) -> None:
        self._apply_sample(sample, notify=True)

    def _apply_sample(self, sample: Sample, *, notify: bool) -> None:
        state = self.data.get(sample.device_id) if self.data else None
        if state is None:
            return
        previous = state.topic_timestamps.get(sample.topic)
        if previous is not None and sample.timestamp < previous:
            return
        state.topic_timestamps[sample.topic] = sample.timestamp
        if state.last_seen is None or sample.timestamp > state.last_seen:
            state.last_seen = sample.timestamp
        if not self.topic_wanted(state, sample.topic):
            if notify:
                self._notify(sample.device_id)
            return
        new_descriptor = False
        flat = flatten_sample_data(sample.data)
        state.last_sample_keys[sample.topic] = frozenset(flat)
        for key, value in flat.items():
            key_id = f"{sample.topic}_{key}"
            if key_id not in state.descriptors:
                descriptor = infer_descriptor(sample.topic, key, value)
                if descriptor is None:
                    continue
                state.descriptors[key_id] = descriptor
                new_descriptor = True
            state.values[key_id] = value
        if new_descriptor:
            self.cache.descriptors[sample.device_id] = dict(state.descriptors)
            self.cache.async_schedule_save()
        if notify:
            self._notify(sample.device_id)
            if new_descriptor:
                self.async_update_listeners()

    @callback
    def _handle_connection(self, connected: bool) -> None:
        if connected:
            self._connections += 1
            outage = (
                time.monotonic() - self._disconnected_at
                if self._disconnected_at is not None
                else None
            )
            self._disconnected_at = None
            # skip the full reseed after blips such as the daily server-side
            # connection recycling; hardly any samples can have been missed
            if self._connections > 1 and (outage is None or outage >= RESEED_MIN_OUTAGE):
                self._schedule_reseed()
        elif self._disconnected_at is None:
            self._disconnected_at = time.monotonic()
        self._update_stream_issue(connected)
        self._notify(HUB_KEY)

    def _schedule_reseed(self) -> None:
        if self._unsub_reseed:
            self._unsub_reseed()

        @callback
        def _start(_now: Any) -> None:
            self._unsub_reseed = None
            self._create_task(self._async_seed(infer=False))

        self._unsub_reseed = async_call_later(self.hass, RESEED_DEBOUNCE, _start)

    @callback
    def _handle_auth_failed(self) -> None:
        self.config_entry.async_start_reauth(self.hass)

    # --- listeners -------------------------------------------------------

    @callback
    def async_add_device_listener(self, key: str, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Register a listener that fires when one device (or the hub) changes."""
        self._device_listeners.setdefault(key, set()).add(listener)

        @callback
        def _remove() -> None:
            listeners = self._device_listeners.get(key)
            if listeners:
                listeners.discard(listener)
                if not listeners:
                    self._device_listeners.pop(key, None)

        return _remove

    @callback
    def _notify(self, key: str) -> None:
        for listener in list(self._device_listeners.get(key, ())):
            listener()

    # --- helpers for platforms ------------------------------------------

    def exclusions_for(self, state: DeviceState) -> frozenset[str]:
        """Excluded data points of a device (device-type rules plus per-device rules)."""
        if not self.excluded:
            return frozenset()
        type_id = state.device.device_type_id
        by_type = self.excluded.get(type_id, frozenset()) if type_id else frozenset()
        by_device = self.excluded.get(f"{DEVICE_TARGET_PREFIX}{state.device.id}", frozenset())
        return by_type | by_device

    @staticmethod
    def is_excluded(exclusions: frozenset[str], topic: str, key: str | None = None) -> bool:
        """Whether a topic (or one data key of it) is excluded by the given rules."""
        if not exclusions:
            return False
        if f"{topic}/{TOPIC_WILDCARD}" in exclusions:
            return True
        return key is not None and f"{topic}/{key}" in exclusions

    def topic_wanted(self, state: DeviceState, topic: str) -> bool:
        """Whether data of this topic is used for the device at all."""
        if self.default_topic_only and topic != DEFAULT_TOPIC:
            return False
        return not self.is_excluded(self.exclusions_for(state), topic)

    def entity_wanted(self, state: DeviceState, descriptor: DataPointDescriptor) -> bool:
        """Whether an entity should exist for this data point given the options."""
        if self.default_topic_only and descriptor.topic != DEFAULT_TOPIC:
            return False
        if self.is_excluded(self.exclusions_for(state), descriptor.topic, descriptor.key):
            return False
        return not (self.data_keys_only and descriptor.key_id not in state.values)

    @staticmethod
    def _key_id_excluded(exclusions: frozenset[str], key_id: str) -> bool:
        """Whether a unique-id suffix ``{topic}_{key}`` matches one of the rules."""
        for rule in exclusions:
            topic, _, key = rule.partition("/")
            if key == TOPIC_WILDCARD:
                if key_id.startswith(f"{topic}_"):
                    return True
            elif key_id == f"{topic}_{key}":
                return True
        return False

    @callback
    def async_purge_excluded_entities(self) -> None:
        """Remove registry entries of data points that are excluded by the options.

        Works on the registry directly so it does not depend on the descriptors
        being loaded yet (devices without a device type only know their data
        points after seeding).
        """
        if not self.excluded or not self.data:
            return
        registry = er.async_get(self.hass)
        removed = 0
        for entry in er.async_entries_for_config_entry(registry, self.config_entry.entry_id):
            unique_id = entry.unique_id
            if not unique_id.startswith(f"{DOMAIN}_"):
                continue
            device_id, _, key_id = unique_id[len(DOMAIN) + 1 :].partition("_")
            state = self.data.get(device_id)
            if state is None or not key_id:
                continue
            exclusions = self.exclusions_for(state)
            if not exclusions:
                continue
            if entry.domain == "device_tracker":
                excluded = key_id.endswith("_position") and self.is_excluded(
                    exclusions, key_id.removesuffix("_position")
                )
            elif entry.domain in ("sensor", "binary_sensor", "event"):
                if entry.domain == "event":
                    key_id = key_id.removesuffix("_event")
                excluded = not key_id.startswith("meta_") and self._key_id_excluded(
                    exclusions, key_id
                )
            else:
                excluded = False
            if excluded:
                registry.async_remove(entry.entity_id)
                removed += 1
        if removed:
            _LOGGER.info("Removed %d entities of excluded data points", removed)

    @property
    def stream_connected(self) -> bool:
        """Whether the WebSocket stream is connected."""
        return self.stream.connected

    def devices(self) -> list[AkenzaDevice]:
        """Current devices."""
        return [s.device for s in (self.data or {}).values()]
