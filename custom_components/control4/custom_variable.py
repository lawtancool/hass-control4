"""Expose Composer custom variables as read-only Home Assistant entities."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Control4Entity
from .agents import find_variables_agent_id, list_custom_variables
from .const import (
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_CUSTOM_VARIABLE_DISCOVERY,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_VARIABLES_AGENT_ID,
    DOMAIN,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

VAR_TYPE_NUMBER = frozenset({"Number", "Float"})
VAR_TYPE_SWITCH = frozenset({"Boolean"})
VAR_TYPE_TEXT = frozenset({"String"})
VAR_TYPE_SELECT = frozenset({"Device"})


def _initial_variable_attributes(
    agent_attributes: dict[str, Any], var_name: str
) -> dict[str, Any]:
    """Seed an entity with only its own variable value, not the full agent bag."""
    for key in (var_name, var_name.upper()):
        if key in agent_attributes:
            return {key: agent_attributes[key]}
    return {}


@dataclass
class CustomVariableDiscovery:
    """Custom variable entities grouped by platform."""

    numbers: list[Control4CustomVariableNumber]
    switches: list[Control4CustomVariableSwitch]
    texts: list[Control4CustomVariableText]
    selects: list[Control4CustomVariableSelect]
    sensors: list[Control4CustomVariableSensor]


async def discover_custom_variables(
    hass: HomeAssistant, entry: ConfigEntry, *, force: bool = False
) -> CustomVariableDiscovery | None:
    """Discover Composer custom variables and build typed read-only entities."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    if not force and CONF_CUSTOM_VARIABLE_DISCOVERY in entry_data:
        return entry_data[CONF_CUSTOM_VARIABLE_DISCOVERY]

    variables_agent_id = entry_data.get(CONF_VARIABLES_AGENT_ID)
    if variables_agent_id is None:
        variables_agent_id = find_variables_agent_id(
            entry_data[CONF_DIRECTOR_ALL_ITEMS]
        )
        entry_data[CONF_VARIABLES_AGENT_ID] = variables_agent_id

    if variables_agent_id is None:
        _LOGGER.warning(
            "Control4 Variables agent not found; custom variable entities not created"
        )
        return None

    director = entry_data[CONF_DIRECTOR]
    var_defs = await list_custom_variables(director, variables_agent_id)
    agent_attrs = await director_get_entry_variables(hass, entry, variables_agent_id)
    parent_id = next(
        (
            item.get("parentId", 1)
            for item in entry_data[CONF_DIRECTOR_ALL_ITEMS]
            if item.get("id") == variables_agent_id
        ),
        1,
    )

    discovery = CustomVariableDiscovery([], [], [], [], [])
    for var_def in var_defs:
        if var_def.get("hidden"):
            continue
        var_name = var_def.get("varName") or var_def.get("name")
        variable_id = var_def.get("variableId")
        if not var_name or variable_id is None:
            continue

        var_type = var_def.get("type")
        common = dict(
            entry_data=entry_data,
            entry=entry,
            var_name=str(var_name),
            variable_id=int(variable_id),
            var_type=var_type,
            variables_agent_id=variables_agent_id,
            parent_id=parent_id,
            agent_attributes=_initial_variable_attributes(agent_attrs, str(var_name)),
        )

        if var_type in VAR_TYPE_NUMBER:
            discovery.numbers.append(Control4CustomVariableNumber(**common))
        elif var_type in VAR_TYPE_SWITCH:
            discovery.switches.append(Control4CustomVariableSwitch(**common))
        elif var_type in VAR_TYPE_TEXT:
            discovery.texts.append(Control4CustomVariableText(**common))
        elif var_type in VAR_TYPE_SELECT:
            discovery.selects.append(Control4CustomVariableSelect(**common))
        else:
            discovery.sensors.append(Control4CustomVariableSensor(**common))

    total = (
        len(discovery.numbers)
        + len(discovery.switches)
        + len(discovery.texts)
        + len(discovery.selects)
        + len(discovery.sensors)
    )
    if total:
        _LOGGER.info(
            "Discovered %d Composer custom variables "
            "(number=%d switch=%d text=%d select=%d sensor=%d; disabled by default)",
            total,
            len(discovery.numbers),
            len(discovery.switches),
            len(discovery.texts),
            len(discovery.selects),
            len(discovery.sensors),
        )
    entry_data[CONF_CUSTOM_VARIABLE_DISCOVERY] = discovery
    return discovery


class _Control4CustomVariableBase(Control4Entity):
    """Shared base for one Composer custom variable (WebSocket push)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_registry_enabled_default = False

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        var_name: str,
        variable_id: int,
        var_type: str | None,
        variables_agent_id: int,
        parent_id: int,
        agent_attributes: dict[str, Any],
    ) -> None:
        """Initialize the entity."""
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
        self._variable_id = variable_id
        self._var_type = var_type
        self._variables_agent_id = variables_agent_id
        self._attr_unique_id = f"{entry.entry_id}_var_{variable_id}"

    def _variable_value(self) -> Any:
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
            name="Variables",
            via_device=(DOMAIN, controller_id),
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose metadata for this variable only."""
        return {
            **self._extra_state_attributes,
            "variable_name": self._var_name,
            "variable_id": self._variable_id,
            "variable_type": self._var_type,
            "variables_agent_id": self._variables_agent_id,
        }

    async def _data_to_extra_state_attributes(self, data) -> None:
        """Keep only this variable's value from a Variables-agent push."""
        if not isinstance(data, dict):
            return
        for key, value in data.items():
            if key in (self._var_name, self._var_name.upper()):
                self._extra_state_attributes[key] = value
                return
            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if sub_key in (self._var_name, self._var_name.upper()):
                        self._extra_state_attributes[sub_key] = sub_value
                        return
            elif key.upper() == self._var_name.upper():
                self._extra_state_attributes[self._var_name.upper()] = value
                return


class Control4CustomVariableNumber(_Control4CustomVariableBase, NumberEntity):
    """Read-only number for a Composer Number/Float custom variable."""

    _attr_mode = NumberMode.AUTO

    @property
    def native_value(self) -> float | None:
        """Return the current numeric value."""
        raw = self._variable_value()
        if raw is None:
            return None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None


class Control4CustomVariableSwitch(_Control4CustomVariableBase, SwitchEntity):
    """Read-only switch for a Composer Boolean custom variable."""

    @property
    def is_on(self) -> bool | None:
        """Return whether the variable is true."""
        raw = self._variable_value()
        if raw is None:
            return None
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        return str(raw).lower() in ("1", "true", "yes", "on")


class Control4CustomVariableText(_Control4CustomVariableBase, TextEntity):
    """Read-only text for a Composer String custom variable."""

    _attr_native_max = 255

    @property
    def native_value(self) -> str | None:
        """Return the current string value."""
        raw = self._variable_value()
        if raw is None:
            return None
        return str(raw)


class Control4CustomVariableSelect(_Control4CustomVariableBase, SelectEntity):
    """Read-only select for a Composer Device custom variable."""

    @property
    def current_option(self) -> str | None:
        """Return the selected device id as a string."""
        raw = self._variable_value()
        if raw is None:
            return None
        return str(raw)

    @property
    def options(self) -> list[str]:
        """Expose the current value as the only option (device list not on REST API)."""
        current = self.current_option
        return [current] if current is not None else []


class Control4CustomVariableSensor(_Control4CustomVariableBase, SensorEntity):
    """Read-only sensor for unknown or unsupported Composer custom variable types."""

    @property
    def native_value(self) -> Any:
        """Return the current variable value."""
        return self._variable_value()


async def async_setup_custom_variable_numbers(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only number entities for Number/Float custom variables."""
    discovery = await discover_custom_variables(hass, entry)
    if discovery and discovery.numbers:
        async_add_entities(discovery.numbers)


async def async_setup_custom_variable_switches(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only switch entities for Boolean custom variables."""
    discovery = await discover_custom_variables(hass, entry)
    if discovery and discovery.switches:
        async_add_entities(discovery.switches)


async def async_setup_custom_variable_texts(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only text entities for String custom variables."""
    discovery = await discover_custom_variables(hass, entry)
    if discovery and discovery.texts:
        async_add_entities(discovery.texts)


async def async_setup_custom_variable_selects(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only select entities for Device custom variables."""
    discovery = await discover_custom_variables(hass, entry)
    if discovery and discovery.selects:
        async_add_entities(discovery.selects)


async def async_setup_custom_variable_sensors(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up read-only sensor entities for unsupported custom variable types."""
    discovery = await discover_custom_variables(hass, entry)
    if discovery and discovery.sensors:
        async_add_entities(discovery.sensors)
