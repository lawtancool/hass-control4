"""Expose selected Composer custom variables as Home Assistant sensors."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Control4Entity
from .agents import configured_option_names, find_variables_agent_id
from .const import (
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_CUSTOM_VAR_NAME_KEYS,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_VARIABLES_AGENT_ID,
    DOMAIN,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up custom variable sensors for a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    var_names = configured_option_names(entry.options, CONF_CUSTOM_VAR_NAME_KEYS)
    if not var_names:
        return

    variables_agent_id = entry_data.get(CONF_VARIABLES_AGENT_ID)
    if variables_agent_id is None:
        variables_agent_id = find_variables_agent_id(
            entry_data[CONF_DIRECTOR_ALL_ITEMS]
        )
        entry_data[CONF_VARIABLES_AGENT_ID] = variables_agent_id

    if variables_agent_id is None:
        _LOGGER.warning(
            "Control4 Variables agent not found; custom variable sensors not created"
        )
        return

    agent_attrs = await director_get_entry_variables(
        hass, entry, variables_agent_id
    )
    parent_id = next(
        (
            item.get("parentId", 1)
            for item in entry_data[CONF_DIRECTOR_ALL_ITEMS]
            if item.get("id") == variables_agent_id
        ),
        1,
    )

    entities = [
        Control4CustomVariableSensor(
            entry_data=entry_data,
            entry=entry,
            var_name=name,
            variables_agent_id=variables_agent_id,
            parent_id=parent_id,
            agent_attributes=agent_attrs,
        )
        for name in var_names
    ]
    async_add_entities(entities)


class Control4CustomVariableSensor(Control4Entity, SensorEntity):
    """Sensor for one Composer custom variable (WebSocket push from Variables agent)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        var_name: str,
        variables_agent_id: int,
        parent_id: int,
        agent_attributes: dict[str, Any],
    ) -> None:
        """Initialize the sensor."""
        super().__init__(
            entry_data,
            entry,
            var_name,
            variables_agent_id,
            "Control4",
            "Variables agent",
            "Variables agent",
            parent_id,
            None,
            agent_attributes,
        )
        self._var_name = var_name
        self._variables_agent_id = variables_agent_id
        self._attr_unique_id = f"{entry.entry_id}_custom_var_{var_name}"

    @property
    def native_value(self) -> Any:
        """Return the current variable value from the latest Variables-agent push."""
        attrs = self.extra_state_attributes
        if self._var_name in attrs:
            return attrs[self._var_name]
        return attrs.get(self._var_name.upper())

    @property
    def available(self) -> bool:  # type: ignore[override]
        if not super().available:
            return False
        attrs = self.extra_state_attributes
        return self._var_name in attrs or self._var_name.upper() in attrs

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to a synthetic Variables agent device."""
        controller_id = self.entry_data[CONF_CONTROLLER_UNIQUE_ID]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.entry.entry_id}_variables_agent")},
            manufacturer="Control4",
            model="Variables agent",
            name="Control4 Variables",
            via_device=(DOMAIN, controller_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose agent metadata alongside variable values."""
        base = super().extra_state_attributes
        return {
            **base,
            "variable_name": self._var_name,
            "variables_agent_id": self._variables_agent_id,
        }
