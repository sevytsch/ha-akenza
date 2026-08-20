"""Coordinator: metadata polling, background seeding and live WebSocket push."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Iterable
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import device_registry as dr
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
    CONF_DEFAULT_TOPIC_ONLY,
    CONF_DEVICE_IMAGES,
    CONF_ENABLE_HIDDEN_KPIS,
    CONF_ORGANIZATION_ID,
    CONF_ORGANIZATION_NAME,
    CONF_POLL_INTERVAL,
    CONF_TAG_IDS,
    CONF_WORKSPACE_IDS,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_TOPIC,
    DIAGNOSTIC_TOPIC_PREFIXES,
    DISABLED_TOPICS,
    DOMAIN,
    MAX_BACKFILL_TOPICS,
    RESEED_DEBOUNCE,
    SEED_CONCURRENCY,
    SEED_NOTIFY_EVERY,
    SEED_SAMPLE_LIMIT,
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
        self._unavailable_types: set[str] = set()
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

    def _effective_workspace_ids(self) -> list[str]:
        if self.workspace_ids:
            if self._access_ids is None:
                return self.workspace_ids
            return [w for w in self.workspace_ids if w in self._access_ids]
        return list(self._access_ids or [])

    async def _async_update_data(self) -> dict[str, DeviceState]:
        """Metadata refresh: device list, device types, online state."""
        try:
            devices = await self.client.async_list_devices(
                self.organization_id, self._effective_workspace_ids()
            )
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
            self._remove_devices(removed)
        self.stream.set_asset_ids(states.keys(), self._create_task)
        return states

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
            except (AkenzaForbiddenError, AkenzaNotFoundError) as err:
                _LOGGER.debug("Device type %s not accessible: %s", type_id, err)
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
            entry = registry.async_get_device(identifiers={(DOMAIN, device_id)})
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
            except (AkenzaForbiddenError, AkenzaNotFoundError, AkenzaConnectionError) as err:
                _LOGGER.debug("infer-schema for %s failed: %s", device_id, err)
                schema = {}
            inferred = descriptors_from_schemas(schema, inferred=True)
            state.descriptors = merge_descriptors(
                self._type_descriptors(state.device_type), inferred, state.descriptors
            )
        try:
            samples = await self.client.async_query_latest(device_id, SEED_SAMPLE_LIMIT)
        except (AkenzaForbiddenError, AkenzaConnectionError) as err:
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
            and not (self.default_topic_only and d.topic != DEFAULT_TOPIC)
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
        if self.default_topic_only and sample.topic != DEFAULT_TOPIC:
            if notify:
                self._notify(sample.device_id)
            return
        new_descriptor = False
        for key, value in flatten_sample_data(sample.data).items():
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
            if self._connections > 1:
                self._schedule_reseed()
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

    @property
    def stream_connected(self) -> bool:
        """Whether the WebSocket stream is connected."""
        return self.stream.connected

    def devices(self) -> list[AkenzaDevice]:
        """Current devices."""
        return [s.device for s in (self.data or {}).values()]
