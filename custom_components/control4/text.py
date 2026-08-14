"""Platform for Control4 custom variable text entities."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .custom_variable import async_setup_custom_variable_texts


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only text entities for String custom variables."""
    await async_setup_custom_variable_texts(hass, entry, async_add_entities)
