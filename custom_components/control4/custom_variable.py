"""Expose selected Composer custom variables as Home Assistant sensors."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .agents import (
    configured_option_names,
    find_variables_agent_id,
    read_custom_variable,
)
from .const import (
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_CUSTOM_VAR_NAME_KEYS,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_VARIABLES_AGENT_ID,
    DOMAIN,
)

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

    coordinator_key = "custom_variable_coordinator"
    coordinator = entry_data.get(coordinator_key)
    if coordinator is None:

        async def _update() -> dict[str, Any]:
            director = entry_data[CONF_DIRECTOR]
            values: dict[str, Any] = {}
            for name in var_names:
                try:
                    values[name] = await read_custom_variable(
                        director, variables_agent_id, name
                    )
                except Exception:
                    _LOGGER.debug(
                        "Failed reading custom variable %s", name, exc_info=True
                    )
                    values[name] = None
            return values

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN} custom variables",
            update_interval=timedelta(seconds=entry_data[CONF_SCAN_INTERVAL]),
            update_method=_update,
        )
        entry_data[coordinator_key] = coordinator
        await coordinator.async_config_entry_first_refresh()
    else:
        await coordinator.async_request_refresh()

    entities = [
        Control4CustomVariableSensor(
            coordinator=coordinator,
            entry=entry,
            entry_data=entry_data,
            var_name=name,
            variables_agent_id=variables_agent_id,
        )
        for name in var_names
    ]
    async_add_entities(entities)


class Control4CustomVariableSensor(CoordinatorEntity[DataUpdateCoordinator], SensorEntity):
    """Sensor for one Composer custom variable."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: ConfigEntry,
        entry_data: dict,
        var_name: str,
        variables_agent_id: int,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._entry_data = entry_data
        self._var_name = var_name
        self._variables_agent_id = variables_agent_id
        self._attr_name = var_name
        self._attr_unique_id = f"{entry.entry_id}_custom_var_{var_name}"

    @property
    def native_value(self) -> Any:
        """Return the current variable value."""
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(self._var_name)

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to a synthetic Variables agent device."""
        controller_id = self._entry_data[CONF_CONTROLLER_UNIQUE_ID]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._entry.entry_id}_variables_agent")},
            manufacturer="Control4",
            model="Variables agent",
            name="Control4 Variables",
            via_device=(DOMAIN, controller_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose agent metadata for debugging."""
        return {
            "variable_name": self._var_name,
            "variables_agent_id": self._variables_agent_id,
        }
