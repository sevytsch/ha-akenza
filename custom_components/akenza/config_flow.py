"""Config, reauth, reconfigure and options flows for akenza."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
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
)
from .const import (
    CONF_BASE_URL,
    CONF_DATA_KEYS_ONLY,
    CONF_DEFAULT_TOPIC_ONLY,
    CONF_DEVICE_IMAGES,
    CONF_ENABLE_HIDDEN_KPIS,
    CONF_ORGANIZATION_ID,
    CONF_ORGANIZATION_NAME,
    CONF_POLL_INTERVAL,
    CONF_TAG_IDS,
    CONF_WORKSPACE_IDS,
    DEFAULT_BASE_URL,
    DEFAULT_POLL_INTERVAL,
    DOMAIN,
    MAX_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
)
from .models import Organization, Tag, Workspace

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
    schema[vol.Optional(CONF_DEVICE_IMAGES, default=bool(current.get(CONF_DEVICE_IMAGES, True)))] = (
        BooleanSelector()
    )
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


def _clean_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {
        CONF_WORKSPACE_IDS: list(user_input.get(CONF_WORKSPACE_IDS) or []),
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


class AkenzaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the akenza config flow."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise flow state."""
        self._api_key: str | None = None
        self._base_url: str = DEFAULT_BASE_URL
        self._discovery: Discovery | None = None

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
                    return self._create_entry(
                        {CONF_WORKSPACE_IDS: [w.id for w in discovery.workspaces]}
                    )
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
            return self._create_entry(user_input)
        return self.async_show_form(
            step_id="workspaces",
            data_schema=_selection_schema(self._discovery),
            description_placeholders={
                "organization": self._discovery.organization.name,
                "workspace_count": str(len(self._discovery.workspaces)),
            },
        )

    def _create_entry(self, selection: Mapping[str, Any]) -> ConfigFlowResult:
        assert self._discovery is not None and self._api_key is not None
        return self.async_create_entry(
            title=self._discovery.organization.name,
            data={
                CONF_API_KEY: self._api_key,
                CONF_BASE_URL: self._base_url,
                CONF_ORGANIZATION_ID: self._discovery.organization.id,
                CONF_ORGANIZATION_NAME: self._discovery.organization.name,
            },
            options=_clean_options(selection),
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


class AkenzaOptionsFlow(OptionsFlowWithReload):
    """Change workspace / tag selection and behaviour."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the selection form."""
        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(data=_clean_options(user_input))
        try:
            discovery = await async_discover(
                self.hass,
                self.config_entry.data[CONF_API_KEY],
                self.config_entry.data.get(CONF_BASE_URL, DEFAULT_BASE_URL),
            )
        except AkenzaAuthError, AkenzaForbiddenError:
            return self.async_abort(reason="invalid_auth")
        except AkenzaError:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="init",
            data_schema=_selection_schema(
                discovery, current=self.config_entry.options, include_poll=True
            ),
            errors=errors,
            description_placeholders={
                "organization": discovery.organization.name,
                "workspace_count": str(len(discovery.workspaces)),
            },
        )
