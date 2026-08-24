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
    CONF_EXCLUDED_DATA_POINTS,
    CONF_ORGANIZATION_ID,
    CONF_POLL_INTERVAL,
    CONF_TAG_IDS,
    CONF_WORKSPACE_IDS,
    DOMAIN,
)

from .conftest import (
    BASE,
    CAT,
    ERS_ECO_TYPE,
    ORG_ID,
    WS_HOME,
    WS_LAB,
    mock_api,
    paged,
    setup_integration,
)


async def test_user_flow_multi_workspace(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_stream: None
) -> None:
    """Key -> workspace selection -> entry."""
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret", CONF_BASE_URL: BASE}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "workspaces"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_WORKSPACE_IDS: [WS_HOME], CONF_TAG_IDS: ["7100000000000001"]},
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "import_mode"
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "create"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Org"
    assert result["data"][CONF_API_KEY] == "secret"
    assert result["data"][CONF_ORGANIZATION_ID] == ORG_ID
    assert result["options"][CONF_WORKSPACE_IDS] == [WS_HOME]
    assert result["options"][CONF_TAG_IDS] == ["7100000000000001"]
    assert result["result"].unique_id == ORG_ID


async def test_user_flow_single_workspace_direct(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """With one workspace and no tags the entry is created immediately."""
    aioclient_mock.get(f"{BASE}/v3/organizations", json=paged([{"id": ORG_ID, "name": "Solo"}]))
    aioclient_mock.get(f"{BASE}/v3/workspace-access", json={"all": False, "ids": [WS_HOME]})
    aioclient_mock.get(
        f"{BASE}/v3/workspaces",
        json=paged([{"id": WS_HOME, "name": "Home"}, {"id": WS_LAB, "name": "Lab"}]),
    )
    aioclient_mock.get(f"{BASE}/v3/tags", json=paged([]))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret"}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "import_mode"
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "create"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    # every accessible workspace selected -> stored as "all" (empty list)
    assert result["options"][CONF_WORKSPACE_IDS] == []


async def test_user_flow_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    """invalid_auth, cannot_connect and invalid_url are reported."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "x", CONF_BASE_URL: "ftp://nope"}
    )
    assert result["errors"] == {CONF_BASE_URL: "invalid_url"}

    aioclient_mock.get(f"{BASE}/v3/organizations", status=401, json={"message": "Invalid token"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "x", CONF_BASE_URL: BASE}
    )
    assert result["errors"] == {"base": "invalid_auth"}

    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{BASE}/v3/organizations", exc=TimeoutError())
    with patch("custom_components.akenza.api._sleep"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "x", CONF_BASE_URL: BASE}
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_already_configured(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """The same organization cannot be added twice."""
    mock_config_entry.add_to_hass(hass)
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret", CONF_BASE_URL: BASE}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauth(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry
) -> None:
    """Reauth replaces the key; a key of another org is rejected."""
    mock_config_entry.add_to_hass(hass)
    aioclient_mock.get(
        f"{BASE}/v3/organizations", json=paged([{"id": "9999999999999999", "name": "Other"}])
    )
    aioclient_mock.get(f"{BASE}/v3/workspace-access", json={"all": True, "ids": []})
    aioclient_mock.get(f"{BASE}/v3/workspaces", json=paged([]))
    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "other"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"

    aioclient_mock.clear_requests()
    mock_api(aioclient_mock)
    result = await mock_config_entry.start_reauth_flow(hass)
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_KEY: "new-secret"}
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_API_KEY] == "new-secret"


async def test_options_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """Options are stored and the entry reloads."""
    mock_config_entry.add_to_hass(hass)
    mock_api(aioclient_mock)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "selection"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "selection"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WORKSPACE_IDS: [WS_LAB], CONF_POLL_INTERVAL: 30}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WORKSPACE_IDS] == [WS_LAB]
    assert mock_config_entry.options[CONF_POLL_INTERVAL] == 30


async def test_options_all_workspaces_stored_as_empty(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """Selecting every workspace stores an empty list so new workspaces are included later."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "selection"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_WORKSPACE_IDS: [WS_HOME, WS_LAB]}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_WORKSPACE_IDS] == []


async def test_options_data_points_flow(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """Data points can be excluded per device type and per device; entities are removed."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    assert hass.states.get("sensor.kitchen_humidity") is not None
    assert hass.states.get("sensor.kitchen_battery_level") is not None
    assert hass.states.get("sensor.cat_tracker_battery_level") is not None

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "data_points"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "data_points"
    targets = result["data_schema"].schema["target"].config["options"]
    labels = {o["value"]: o["label"] for o in targets}
    assert labels[ERS_ECO_TYPE] == "ERS Eco Lite LoRa · 1"
    assert labels[f"device:{CAT}"] == "Cat tracker"

    # device type: drop humidity and the whole lifecycle topic
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"target": ERS_ECO_TYPE}
    )
    assert result["step_id"] == "data_point_keys"
    assert result["description_placeholders"]["target"] == "ERS Eco Lite LoRa · 1"
    options = result["data_schema"].schema["keys"].config["options"]
    values = [o["value"] for o in options]
    assert values[0] == "default/*"
    assert "default/humidity" in values and "lifecycle/*" in values
    assert "default · Temperature (temperature)" in {o["label"] for o in options}
    keep = [v for v in values if v not in ("default/humidity", "lifecycle/*")]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"keys": keep})
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "data_points_next"

    # a device without device type: drop its battery level
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "data_points"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"target": f"device:{CAT}"}
    )
    options = result["data_schema"].schema["keys"].config["options"]
    keep = [o["value"] for o in options if o["value"] != "cat/batteryLevel"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"keys": keep})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apply"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert mock_config_entry.options[CONF_EXCLUDED_DATA_POINTS] == {
        ERS_ECO_TYPE: ["default/humidity", "lifecycle/*"],
        f"device:{CAT}": ["cat/batteryLevel"],
    }
    # the reload removed the excluded entities and kept the rest
    assert hass.states.get("sensor.kitchen_humidity") is None
    assert hass.states.get("sensor.kitchen_battery_level") is None
    assert hass.states.get("sensor.kitchen_temperature") is not None
    assert hass.states.get("sensor.cat_tracker_battery_level") is None
    assert hass.states.get("sensor.cat_tracker_at_home") is not None

    # re-enabling everything clears the option
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "data_points"}
    )
    assert result["description_placeholders"]["rules"] == "2"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"target": ERS_ECO_TYPE}
    )
    all_values = [o["value"] for o in result["data_schema"].schema["keys"].config["options"]]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"keys": all_values}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "apply"}
    )
    await hass.async_block_till_done(wait_background_tasks=True)
    assert mock_config_entry.options[CONF_EXCLUDED_DATA_POINTS] == {
        f"device:{CAT}": ["cat/batteryLevel"]
    }
    assert hass.states.get("sensor.kitchen_humidity") is not None


async def test_options_data_points_requires_loaded_entry(
    hass: HomeAssistant,
    aioclient_mock: AiohttpClientMocker,
    mock_config_entry: MockConfigEntry,
    mock_stream: None,
) -> None:
    """Without a loaded entry the data-point step aborts."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "data_points"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"


async def test_user_flow_with_data_points(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_stream: None
) -> None:
    """Data points can be restricted per device type during the initial setup."""
    mock_api(aioclient_mock)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WORKSPACE_IDS: [WS_HOME]}
    )
    assert result["step_id"] == "import_mode"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "load_catalog"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    assert result["progress_action"] == "loading_catalog"
    await hass.async_block_till_done()
    result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "data_points"
    targets = result["data_schema"].schema["target"].config["options"]
    # only device types with a readable schema are offered (404/403 types and untyped devices are not)
    assert [o["value"] for o in targets] == [ERS_ECO_TYPE]
    assert targets[0]["label"] == "ERS Eco Lite LoRa · 1"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"target": ERS_ECO_TYPE}
    )
    assert result["step_id"] == "data_point_keys"
    values = [o["value"] for o in result["data_schema"].schema["keys"].config["options"]]
    assert "default/temperature" in values and "lifecycle/*" in values
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"keys": [v for v in values if v != "lifecycle/*"]}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["step_id"] == "data_points_next"
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "apply"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"][CONF_WORKSPACE_IDS] == [WS_HOME]
    assert result["options"][CONF_EXCLUDED_DATA_POINTS] == {ERS_ECO_TYPE: ["lifecycle/*"]}


async def test_user_flow_catalog_unavailable_imports_everything(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_stream: None
) -> None:
    """If no device type offers a schema the flow falls back to importing everything."""
    mock_api(aioclient_mock)
    aioclient_mock.clear_requests()
    mock_api(aioclient_mock, assets=paged([]))
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_API_KEY: "secret"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_WORKSPACE_IDS: [WS_LAB]}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "load_catalog"}
    )
    assert result["type"] is FlowResultType.SHOW_PROGRESS
    await hass.async_block_till_done()
    with patch("custom_components.akenza.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"])
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_EXCLUDED_DATA_POINTS not in result["options"]
