"""Tests for the config, reauth, reconfigure and options flows."""

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.const import (
    CONF_BASE_URL,
    CONF_ORGANIZATION_ID,
    CONF_POLL_INTERVAL,
    CONF_TAG_IDS,
    CONF_WORKSPACE_IDS,
    DOMAIN,
)

from .conftest import BASE, ORG_ID, WS_HOME, WS_LAB, mock_api, paged


async def test_user_flow_multi_workspace(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_stream: None) -> None:
    """Key -> workspace selection -> entry."""
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret", CONF_BASE_URL: BASE}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "workspaces"

    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_WORKSPACE_IDS: [WS_HOME], CONF_TAG_IDS: ["7100000000000001"]},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Org"
    assert result["data"][CONF_API_KEY] == "secret"
    assert result["data"][CONF_ORGANIZATION_ID] == ORG_ID
    assert result["options"][CONF_WORKSPACE_IDS] == [WS_HOME]
    assert result["options"][CONF_TAG_IDS] == ["7100000000000001"]
    assert result["result"].unique_id == ORG_ID


async def test_user_flow_single_workspace_direct(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """With one workspace and no tags the entry is created immediately."""
    aioclient_mock.get(f"{BASE}/v3/organizations", json=paged([{"id": ORG_ID, "name": "Solo"}]))
    aioclient_mock.get(f"{BASE}/v3/workspace-access", json={"all": False, "ids": [WS_HOME]})
    aioclient_mock.get(f"{BASE}/v3/workspaces", json=paged([{"id": WS_HOME, "name": "Home"}, {"id": WS_LAB, "name": "Lab"}]))
    aioclient_mock.get(f"{BASE}/v3/tags", json=paged([]))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "secret"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_WORKSPACE_IDS] == [WS_HOME]


async def test_user_flow_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """invalid_auth, cannot_connect and invalid_url are reported."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "x", CONF_BASE_URL: "ftp://nope"})
    assert result["errors"] == {CONF_BASE_URL: "invalid_url"}

    aioclient_mock.get(f"{BASE}/v3/organizations", status=401, json={"message": "Invalid token"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "x", CONF_BASE_URL: BASE})
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/v3/organizations", exc=TimeoutError())
    with patch("custom_components.akenza.api._sleep"):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "x", CONF_BASE_URL: BASE})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry) -> None:
    """The same organization cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "secret", CONF_BASE_URL: BASE})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry) -> None:
    """Reauth replaces the key; a key of another org is rejected."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(f"{BASE}/v3/organizations", json=paged([{"id": "9999999999999999", "name": "Other"}]))
    aioclient_mock.get(f"{BASE}/v3/workspace-access", json={"all": True, "ids": []})
    aioclient_mock.get(f"{BASE}/v3/workspaces", json=paged([]))
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "other"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    result = await mock_config_entry.start_reauth_flow(hass)
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "new-secret"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "new-secret"


async def test_options_flow(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None) -> None:
    """Options are stored and the entry reloads."""
    mock_config_entry.add_to_hass(hass)
    mock_api(aioclient_mock)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WORKSPACE_IDS: [WS_LAB], CONF_POLL_INTERVAL: 30}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WORKSPACE_IDS] == [WS_LAB]
    assert mock_config_entry.options[CONF_POLL_INTERVAL] == 30
