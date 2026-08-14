"""Expose Composer macros as Home Assistant buttons."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .agents import execute_macro, find_macros_agent_id, list_macros
from .const import (
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_MACROS_AGENT_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up macro buttons for a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    macros_agent_id = entry_data.get(CONF_MACROS_AGENT_ID)
    if macros_agent_id is None:
        macros_agent_id = find_macros_agent_id(entry_data[CONF_DIRECTOR_ALL_ITEMS])
        entry_data[CONF_MACROS_AGENT_ID] = macros_agent_id

    if macros_agent_id is None:
        _LOGGER.warning("Control4 Macros agent not found; macro buttons not created")
        return

    director = entry_data[CONF_DIRECTOR]
    macros = await list_macros(director)
    entities: list[Control4MacroButton] = []

    for macro in macros:
        macro_id = macro.get("id")
        macro_name = macro.get("name")
        if macro_id is None or not macro_name:
            continue
        entities.append(
            Control4MacroButton(
                entry=entry,
                entry_data=entry_data,
                macro_id=int(macro_id),
                macro_name=str(macro_name),
                macros_agent_id=macros_agent_id,
            )
        )

    if entities:
        _LOGGER.info(
            "Discovered %d Composer macros (entities disabled by default)",
            len(entities),
        )
        async_add_entities(entities)


class Control4MacroButton(ButtonEntity):
    """Button that executes one Composer macro."""

    _attr_has_entity_name = True
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        entry: ConfigEntry,
        entry_data: dict,
        macro_id: int,
        macro_name: str,
        macros_agent_id: int,
    ) -> None:
        """Initialize the button."""
        self._entry = entry
        self._entry_data = entry_data
        self._macro_id = macro_id
        self._macro_name = macro_name
        self._macros_agent_id = macros_agent_id
        self._attr_name = macro_name
        self._attr_unique_id = f"{entry.entry_id}_macro_{macro_id}"

    async def async_press(self) -> None:
        """Execute the macro."""
        director = self._entry_data[CONF_DIRECTOR]
        await execute_macro(director, self._macros_agent_id, self._macro_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to a synthetic Macros agent device."""
        controller_id = self._entry_data[CONF_CONTROLLER_UNIQUE_ID]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_macros_agent")},
            manufacturer="Control4",
            model="Macros agent",
            name="Macros",
            via_device=(DOMAIN, controller_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, int | str]:
        """Expose macro metadata for debugging."""
        return {
            "macro_id": self._macro_id,
            "macro_name": self._macro_name,
            "macros_agent_id": self._macros_agent_id,
        }
