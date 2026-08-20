"""Tests for diagnostics redaction."""

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.diagnostics import async_get_config_entry_diagnostics

from .conftest import setup_integration


async def test_diagnostics_redacts_secrets(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """API key and physical device ids are redacted."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)
    assert diag["entry"]["data"]["api_key"] == "**REDACTED**"
    assert "secret-key" not in str(diag)
    assert "A1B2C3D4E5F60001" not in str(diag)
    assert len(diag["devices"]) == 5
    kitchen = next(d for d in diag["devices"] if d["device"]["name"] == "Kitchen")
    assert kitchen["values"]["default_temperature"] == 27.8
