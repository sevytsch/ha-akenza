"""Config, reauth, reconfigure and options flows for akenza."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    AkenzaApiClient,
    AkenzaAuthError,
    AkenzaConnectionError,
    AkenzaError,
    AkenzaForbiddenError,
    AkenzaNotFoundError,
)
from .const import (
    CONF_BASE_URL,
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
    DEFAULT_BASE_URL,
    DEFAULT_POLL_INTERVAL,
    DEVICE_TARGET_PREFIX,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    TOPIC_WILDCARD,
)
from .models import DataPointDescriptor, Organization, Tag, Workspace
from .schema import descriptors_from_schemas

if TYPE_CHECKING:
    from .coordinator import AkenzaCoordinator

MAX_TAG_WORKSPACES = 50


@dataclass
class Discovery:
    """What we learn from an API key."""

    organization: Organization
    workspaces: list[Workspace] = field(default_factory=list)
    tags: list[Tag] = field(default_factory=list)


async def async_discover(hass: HomeAssistant, api_key: str, base_url: str) -> Discovery:
    """Validate the key and discover organization, workspaces and tags."""
    client = AkenzaApiClient(async_get_clientsession(hass), api_key, base_url)
    organization = await client.async_get_organization()
    try:
        access = await client.async_get_workspace_access(organization.id)
        allowed: set[str] | None = None if access.all else set(access.ids)
    except AkenzaForbiddenError:
        allowed = None
    try:
        workspaces = await client.async_list_workspaces(organization.id)
    except AkenzaForbiddenError:
        workspaces = []
    if allowed is not None:
        workspaces = [w for w in workspaces if w.id in allowed]
        known = {w.id for w in workspaces}
        workspaces.extend(Workspace(id=w, name=w) for w in sorted(allowed) if w not in known)
    tags: list[Tag] = []
    for workspace in workspaces[:MAX_TAG_WORKSPACES]:
        try:
            tags.extend(await client.async_list_tags(workspace.id))
        except AkenzaForbiddenError:
            continue
    return Discovery(organization=organization, workspaces=workspaces, tags=tags)


def _selection_schema(
    discovery: Discovery,
    *,
    current: Mapping[str, Any] | None = None,
    include_poll: bool = False,
) -> vol.Schema:
    current = current or {}
    workspace_names = {w.id: w.name for w in discovery.workspaces}
    workspace_options = [SelectOptionDict(value=w.id, label=w.name) for w in discovery.workspaces]
    tag_options = [
        SelectOptionDict(
            value=t.id,
            label=f"{workspace_names.get(t.workspace_id, t.workspace_id)} · {t.name}",
        )
        for t in discovery.tags
    ]
    schema: dict[Any, Any] = {
        vol.Optional(
            CONF_WORKSPACE_IDS,
            default=list(current.get(CONF_WORKSPACE_IDS) or [w.id for w in discovery.workspaces]),
        ): SelectSelector(
            SelectSelectorConfig(
                options=workspace_options,
                multiple=True,
                mode=SelectSelectorMode.DROPDOWN,
                sort=True,
            )
        ),
    }
    if tag_options:
        schema[vol.Optional(CONF_TAG_IDS, default=list(current.get(CONF_TAG_IDS) or []))] = (
            SelectSelector(
                SelectSelectorConfig(
                    options=tag_options,
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                    sort=True,
                )
            )
        )
    schema[
        vol.Optional(
            CONF_DEFAULT_TOPIC_ONLY, default=bool(current.get(CONF_DEFAULT_TOPIC_ONLY, False))
        )
    ] = BooleanSelector()
    schema[
        vol.Optional(
            CONF_ENABLE_HIDDEN_KPIS, default=bool(current.get(CONF_ENABLE_HIDDEN_KPIS, False))
        )
    ] = BooleanSelector()
    schema[
        vol.Optional(CONF_DEVICE_IMAGES, default=bool(current.get(CONF_DEVICE_IMAGES, True)))
    ] = BooleanSelector()
    schema[
        vol.Optional(CONF_DATA_KEYS_ONLY, default=bool(current.get(CONF_DATA_KEYS_ONLY, False)))
    ] = BooleanSelector()
    if include_poll:
        schema[
            vol.Optional(
                CONF_POLL_INTERVAL,
                default=int(current.get(CONF_POLL_INTERVAL) or DEFAULT_POLL_INTERVAL),
            )
        ] = NumberSelector(
            NumberSelectorConfig(
                min=MIN_POLL_INTERVAL,
                max=MAX_POLL_INTERVAL,
                step=1,
                mode=NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        )
    return vol.Schema(schema)


def _clean_options(
    user_input: Mapping[str, Any], *, all_workspace_ids: Iterable[str] = ()
) -> dict[str, Any]:
    workspace_ids = list(user_input.get(CONF_WORKSPACE_IDS) or [])
    if all_workspace_ids and set(workspace_ids) >= set(all_workspace_ids):
        # "all workspaces" is stored as an empty list so that workspaces created
        # later are picked up automatically
        workspace_ids = []
    options: dict[str, Any] = {
        CONF_WORKSPACE_IDS: workspace_ids,
        CONF_TAG_IDS: list(user_input.get(CONF_TAG_IDS) or []),
        CONF_DEFAULT_TOPIC_ONLY: bool(user_input.get(CONF_DEFAULT_TOPIC_ONLY, False)),
        CONF_ENABLE_HIDDEN_KPIS: bool(user_input.get(CONF_ENABLE_HIDDEN_KPIS, False)),
        CONF_DEVICE_IMAGES: bool(user_input.get(CONF_DEVICE_IMAGES, True)),
        CONF_DATA_KEYS_ONLY: bool(user_input.get(CONF_DATA_KEYS_ONLY, False)),
    }
    if CONF_POLL_INTERVAL in user_input:
        options[CONF_POLL_INTERVAL] = int(user_input[CONF_POLL_INTERVAL])
    return options


def _credentials_schema(*, base_url: str = DEFAULT_BASE_URL) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_API_KEY): TextSelector(
                TextSelectorConfig(type=TextSelectorType.PASSWORD)
            ),
            vol.Optional(CONF_BASE_URL, default=base_url): TextSelector(
                TextSelectorConfig(type=TextSelectorType.URL)
            ),
        }
    )


def _normalize_base_url(value: str | None) -> str:
    url = (value or DEFAULT_BASE_URL).strip().rstrip("/")
    if not url.startswith(("https://", "http://")):
        raise vol.Invalid("invalid_url")
    return url


@dataclass
class CatalogEntry:
    """One target of the data-point selection (a device type or a single device)."""

    label: str
    descriptors: dict[str, DataPointDescriptor] = field(default_factory=dict)


type DataPointCatalog = dict[str, CatalogEntry]


def _catalog_from_coordinator(coordinator: AkenzaCoordinator) -> DataPointCatalog:
    """Targets and their known data points from the running integration."""
    types: dict[str, tuple[str, int, dict[str, DataPointDescriptor]]] = {}
    devices: dict[str, CatalogEntry] = {}
    for state in coordinator.data.values():
        device = state.device
        if device.device_type_id:
            name = (
                state.device_type.name
                if state.device_type
                else device.device_type_name or device.device_type_id
            )
            _name, count, descriptors = types.get(device.device_type_id, (name, 0, {}))
            for descriptor in state.descriptors.values():
                descriptors.setdefault(descriptor.key_id, descriptor)
            types[device.device_type_id] = (name, count + 1, descriptors)
        else:
            devices[f"{DEVICE_TARGET_PREFIX}{device.id}"] = CatalogEntry(
                device.name, dict(state.descriptors)
            )
    catalog: DataPointCatalog = {
        type_id: CatalogEntry(f"{name} · {count}", descriptors)
        for type_id, (name, count, descriptors) in sorted(
            types.items(), key=lambda i: i[1][0].lower()
        )
    }
    catalog.update(sorted(devices.items(), key=lambda i: i[1].label.lower()))
    return catalog


async def _async_catalog_from_api(
    client: AkenzaApiClient,
    organization_id: str,
    workspace_ids: Iterable[str],
    tag_ids: Iterable[str],
) -> DataPointCatalog:
    """Targets and data points from the device-type schemas (initial setup)."""
    devices = await client.async_list_devices(organization_id, list(workspace_ids))
    tags = set(tag_ids)
    if tags:
        devices = [d for d in devices if d.tag_ids & tags]
    counts: dict[str, int] = {}
    for device in devices:
        if device.device_type_id:
            counts[device.device_type_id] = counts.get(device.device_type_id, 0) + 1

    async def load(type_id: str) -> tuple[str, CatalogEntry | None]:
        try:
            device_type = await client.async_get_device_type(type_id)
        except AkenzaForbiddenError, AkenzaNotFoundError:
            return type_id, None
        descriptors = descriptors_from_schemas(device_type.schemas)
        if not descriptors:
            return type_id, None
        return type_id, CatalogEntry(f"{device_type.name} · {counts[type_id]}", descriptors)

    loaded = await asyncio.gather(*(load(t) for t in counts))
    return {
        type_id: entry
        for type_id, entry in sorted(loaded, key=lambda i: i[1].label.lower() if i[1] else "")
        if entry is not None
    }


def _data_point_options(descriptors: Iterable[DataPointDescriptor]) -> list[SelectOptionDict]:
    """All data points of one target, grouped by topic, with a wildcard per topic."""
    by_id: dict[str, DataPointDescriptor] = {}
    for descriptor in descriptors:
        by_id.setdefault(descriptor.key_id, descriptor)
    topics = sorted({d.topic for d in by_id.values()}, key=lambda t: (t != "default", t))
    options: list[SelectOptionDict] = []
    for topic in topics:
        options.append(SelectOptionDict(value=f"{topic}/{TOPIC_WILDCARD}", label=f"{topic} · *"))
        for descriptor in sorted(
            (d for d in by_id.values() if d.topic == topic),
            key=lambda d: (d.title or d.key).lower(),
        ):
            title = descriptor.title or descriptor.key
            label = (
                f"{topic} · {title}"
                if title == descriptor.key
                else f"{topic} · {title} ({descriptor.key})"
            )
            options.append(SelectOptionDict(value=f"{topic}/{descriptor.key}", label=label))
    return options


class DataPointSteps:
    """Steps shared by the config and options flows: pick a target, select its data points."""

    hass: HomeAssistant
    _catalog: DataPointCatalog | None = None
    _excluded: dict[str, list[str]] | None = None
    _target: str | None = None

    async def _async_apply_data_points(self) -> ConfigFlowResult:
        raise NotImplementedError

    def _excluded_option(self) -> dict[str, list[str]] | None:
        """Exclusions to store (None = nothing selected)."""
        if not self._excluded:
            return None
        return {k: list(v) for k, v in self._excluded.items() if v}

    async def async_step_data_points(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the device type (or device) whose data points to configure."""
        if not self._catalog:
            return self.async_abort(reason="not_loaded")
        if self._excluded is None:
            self._excluded = {}
        targets = [SelectOptionDict(value=k, label=v.label) for k, v in self._catalog.items()]
        if user_input and user_input.get("target"):
            self._target = str(user_input["target"])
            return await self.async_step_data_point_keys()
        return self.async_show_form(
            step_id="data_points",
            data_schema=vol.Schema(
                {
                    vol.Required("target"): SelectSelector(
                        SelectSelectorConfig(options=targets, mode=SelectSelectorMode.DROPDOWN)
                    )
                }
            ),
            description_placeholders={"rules": str(len(self._excluded))},
        )

    async def async_step_data_point_keys(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select which data points of the chosen target are used."""
        if not self._catalog or self._target is None or self._excluded is None:
            return self.async_abort(reason="not_loaded")
        entry = self._catalog[self._target]
        options = _data_point_options(entry.descriptors.values())
        if user_input is not None and "keys" in user_input:
            selected = set(user_input.get("keys") or [])
            excluded = sorted(o["value"] for o in options if o["value"] not in selected)
            if excluded:
                self._excluded[self._target] = excluded
            else:
                self._excluded.pop(self._target, None)
            return await self.async_step_data_points_next()
        current = set(self._excluded.get(self._target, []))
        return self.async_show_form(
            step_id="data_point_keys",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "keys", default=[o["value"] for o in options if o["value"] not in current]
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options, multiple=True, mode=SelectSelectorMode.LIST
                        )
                    )
                }
            ),
            description_placeholders={"target": entry.label, "count": str(len(options))},
        )

    async def async_step_data_points_next(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure another target or apply."""
        return self.async_show_menu(
            step_id="data_points_next", menu_options=["data_points", "apply"]
        )

    async def async_step_apply(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Store the data-point rules."""
        return await self._async_apply_data_points()


class AkenzaConfigFlow(DataPointSteps, ConfigFlow, domain=DOMAIN):
    """Handle the akenza config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._api_key: str | None = None
        self._base_url: str = DEFAULT_BASE_URL
        self._discovery: Discovery | None = None
        self._selection: dict[str, Any] = {}
        self._catalog_task: asyncio.Task[DataPointCatalog] | None = None
        self._catalog = None
        self._excluded = None
        self._target = None

    async def _async_validate(
        self, user_input: Mapping[str, Any], errors: dict[str, str]
    ) -> Discovery | None:
        try:
            base_url = _normalize_base_url(user_input.get(CONF_BASE_URL))
        except vol.Invalid:
            errors[CONF_BASE_URL] = "invalid_url"
            return None
        api_key = str(user_input[CONF_API_KEY]).strip()
        try:
            discovery = await async_discover(self.hass, api_key, base_url)
        except AkenzaAuthError, AkenzaForbiddenError:
            errors["base"] = "invalid_auth"
        except AkenzaConnectionError:
            errors["base"] = "cannot_connect"
        except AkenzaError:
            errors["base"] = "unknown"
        else:
            self._api_key = api_key
            self._base_url = base_url
            self._discovery = discovery
            return discovery
        return None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> AkenzaOptionsFlow:
        """Return the options flow."""
        return AkenzaOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Ask for the API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            discovery = await self._async_validate(user_input, errors)
            if discovery is not None:
                await self.async_set_unique_id(discovery.organization.id)
                self._abort_if_unique_id_configured()
                if len(discovery.workspaces) <= 1 and not discovery.tags:
                    self._selection = {CONF_WORKSPACE_IDS: [w.id for w in discovery.workspaces]}
                    return await self.async_step_import_mode()
                return await self.async_step_workspaces()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _credentials_schema(), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_workspaces(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select workspaces / tags."""
        assert self._discovery is not None
        if user_input is not None:
            self._selection = dict(user_input)
            return await self.async_step_import_mode()
        return self.async_show_form(
            step_id="workspaces",
            data_schema=_selection_schema(self._discovery),
            description_placeholders={
                "organization": self._discovery.organization.name,
                "workspace_count": str(len(self._discovery.workspaces)),
            },
        )

    async def async_step_import_mode(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Import everything (default) or restrict data points per device type first."""
        return self.async_show_menu(step_id="import_mode", menu_options=["create", "load_catalog"])

    async def async_step_create(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create the entry with everything imported."""
        return self._create_entry()

    async def async_step_load_catalog(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Load devices and device-type schemas of the selection (with progress)."""
        assert self._discovery is not None and self._api_key is not None
        if self._catalog_task is None:
            selected = list(self._selection.get(CONF_WORKSPACE_IDS) or []) or [
                w.id for w in self._discovery.workspaces
            ]
            client = AkenzaApiClient(
                async_get_clientsession(self.hass), self._api_key, self._base_url
            )
            self._catalog_task = self.hass.async_create_task(
                _async_catalog_from_api(
                    client,
                    self._discovery.organization.id,
                    selected,
                    self._selection.get(CONF_TAG_IDS) or [],
                ),
                eager_start=False,
            )
        if not self._catalog_task.done():
            return self.async_show_progress(
                step_id="load_catalog",
                progress_action="loading_catalog",
                progress_task=self._catalog_task,
            )
        try:
            self._catalog = self._catalog_task.result()
        except AkenzaError:
            self._catalog = {}
        self._catalog_task = None
        if not self._catalog:
            return self.async_show_progress_done(next_step_id="no_catalog")
        return self.async_show_progress_done(next_step_id="data_points")

    async def async_step_no_catalog(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """No device types with a schema (or loading failed): import everything."""
        return self._create_entry()

    async def _async_apply_data_points(self) -> ConfigFlowResult:
        return self._create_entry()

    def _create_entry(self) -> ConfigFlowResult:
        assert self._discovery is not None and self._api_key is not None
        options = _clean_options(
            self._selection, all_workspace_ids=[w.id for w in self._discovery.workspaces]
        )
        excluded = self._excluded_option()
        if excluded:
            options[CONF_EXCLUDED_DATA_POINTS] = excluded
        return self.async_create_entry(
            title=self._discovery.organization.name,
            data={
                CONF_API_KEY: self._api_key,
                CONF_BASE_URL: self._base_url,
                CONF_ORGANIZATION_ID: self._discovery.organization.id,
                CONF_ORGANIZATION_NAME: self._discovery.organization.name,
            },
            options=options,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start reauthentication."""
        self._base_url = entry_data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a new API key."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            discovery = await self._async_validate(
                {**user_input, CONF_BASE_URL: user_input.get(CONF_BASE_URL, self._base_url)}, errors
            )
            if discovery is not None:
                await self.async_set_unique_id(discovery.organization.id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_API_KEY: self._api_key,
                        CONF_BASE_URL: self._base_url,
                        CONF_ORGANIZATION_NAME: discovery.organization.name,
                    },
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_credentials_schema(base_url=self._base_url),
            errors=errors,
            description_placeholders={"organization": entry.title},
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the API key / URL of an existing entry."""
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()
        if user_input is not None:
            discovery = await self._async_validate(user_input, errors)
            if discovery is not None:
                await self.async_set_unique_id(discovery.organization.id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_API_KEY: self._api_key,
                        CONF_BASE_URL: self._base_url,
                        CONF_ORGANIZATION_NAME: discovery.organization.name,
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_credentials_schema(
                base_url=entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL)
            ),
            errors=errors,
            description_placeholders={"organization": entry.title},
        )


class AkenzaOptionsFlow(DataPointSteps, OptionsFlowWithReload):
    """Change workspace / tag selection, behaviour and data-point rules."""

    def __init__(self) -> None:
        """Initialise flow state."""
        self._discovery: Discovery | None = None
        self._catalog = None
        self._excluded = None
        self._target = None

    def _finish(self, updates: Mapping[str, Any]) -> ConfigFlowResult:
        options = {**self.config_entry.options, **updates}
        if self._excluded is not None:
            excluded = self._excluded_option()
            if excluded:
                options[CONF_EXCLUDED_DATA_POINTS] = excluded
            else:
                options.pop(CONF_EXCLUDED_DATA_POINTS, None)
        return self.async_create_entry(data=options)

    async def _async_apply_data_points(self) -> ConfigFlowResult:
        return self._finish({})

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Choose what to configure."""
        return self.async_show_menu(step_id="init", menu_options=["selection", "data_points"])

    async def async_step_selection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Workspaces, tags, behaviour and poll interval."""
        if user_input is not None and self._discovery is not None:
            return self._finish(
                _clean_options(
                    user_input, all_workspace_ids=[w.id for w in self._discovery.workspaces]
                )
            )
        try:
            self._discovery = await async_discover(
                self.hass,
                self.config_entry.data[CONF_API_KEY],
                self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            )
        except AkenzaAuthError, AkenzaForbiddenError:
            return self.async_abort(reason="invalid_auth")
        except AkenzaError:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="selection",
            data_schema=_selection_schema(
                self._discovery, current=self.config_entry.options, include_poll=True
            ),
            description_placeholders={
                "organization": self._discovery.organization.name,
                "workspace_count": str(len(self._discovery.workspaces)),
            },
        )

    async def async_step_data_points(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Load the catalog from the running integration, then continue with the shared step."""
        if self._catalog is None:
            if self.config_entry.state is not ConfigEntryState.LOADED:
                return self.async_abort(reason="not_loaded")
            coordinator: AkenzaCoordinator = self.config_entry.runtime_data
            if not coordinator.data:
                return self.async_abort(reason="not_loaded")
            self._catalog = _catalog_from_coordinator(coordinator)
            self._excluded = {
                str(k): [str(v) for v in values]
                for k, values in (
                    self.config_entry.options.get(CONF_EXCLUDED_DATA_POINTS) or {}
                ).items()
            }
        return await super().async_step_data_points(user_input)
