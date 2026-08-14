"""Platform for Control4 custom variable number entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .custom_variable import async_setup_custom_variable_numbers


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only number entities for Number/Float custom variables."""
    await async_setup_custom_variable_numbers(hass, entry, async_add_entities)
