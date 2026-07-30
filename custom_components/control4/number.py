"""Platform for Control4 pool/spa number entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .pool import async_setup_pool_numbers


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 pool/spa setpoints from a config entry."""
    await async_setup_pool_numbers(hass, entry, async_add_entities)
