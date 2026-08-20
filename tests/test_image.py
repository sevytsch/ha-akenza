"""Tests for the product image platform."""

import respx
from homeassistant.core import HomeAssistant
from httpx import Response
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.akenza.const import CONF_DEVICE_IMAGES

from .conftest import setup_integration

PICTURE = "https://raw.githubusercontent.com/akenza-io/device-type-library/main/types/elsys/ers-eco/erseco.png"


async def test_image_served(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None, hass_client
) -> None:
    """The image proxy serves the device-type picture."""
    await setup_integration(hass, mock_config_entry, aioclient_mock)
    client = await hass_client()
    with respx.mock:
        respx.get(PICTURE).mock(
            return_value=Response(200, content=b"PNGDATA", headers={"Content-Type": "image/png"})
        )
        resp = await client.get(
            hass.states.get("image.kitchen_product_image").attributes["entity_picture"]
        )
    assert resp.status == 200
    assert await resp.read() == b"PNGDATA"
    assert resp.content_type == "image/png"


async def test_images_disabled(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mock_config_entry: MockConfigEntry, mock_stream: None
) -> None:
    """No image entities when the option is off."""
    entry = MockConfigEntry(
        domain=mock_config_entry.domain,
        title=mock_config_entry.title,
        unique_id=mock_config_entry.unique_id,
        data=dict(mock_config_entry.data),
        options={**mock_config_entry.options, CONF_DEVICE_IMAGES: False},
    )
    await setup_integration(hass, entry, aioclient_mock)
    assert hass.states.get("image.kitchen_product_image") is None
    assert hass.states.get("sensor.kitchen_temperature") is not None
