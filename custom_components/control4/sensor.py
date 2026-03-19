"""Platform for Control4 sensors."""
from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Control4Entity
from .const import DOMAIN, CONTROL4_ENTITY_TYPE, CONF_DIRECTOR_ALL_ITEMS
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

@dataclass
class _SensorMap:
    key: str
    name_suffix: str
    unit: str | None
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    value_fn: Callable[[Any], Any] | None = None
    proxies: set[str] | None = None

SENSORS: list[_SensorMap] = [
    # Power/energy (proxy in config)
    _SensorMap(
        key="CURRENT_POWER",
        name_suffix="Power",
        unit="W",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        proxies={"light_v2"},
    ),
    _SensorMap(
        key="ENERGY_USED_TODAY",
        name_suffix="Energy Today",
        unit="Wh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        proxies={"light_v2"},
    ),
    _SensorMap(
        key="ENERGY_USED",
        name_suffix="Energy",
        unit="Wh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        proxies={"light_v2"},
    ),
    # Trigger/level preset (proxy in config)
    _SensorMap(
        key="LEVEL",
        name_suffix="Level",
        unit=None,
        device_class=None,
        state_class=None,
        proxies={"dynalite_trigger"},
    ),
    _SensorMap(
        key="PRESET",
        name_suffix="Preset",
        unit=None,
        device_class=None,
        state_class=None,
        proxies={"dynalite_trigger"},
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]

    director_all_items = entry_data[CONF_DIRECTOR_ALL_ITEMS]
    entities: list[Control4AttrSensor] = []
    unmatched_vars_sample: list[tuple[int, str, list[str]]] = []  # (id, name, var_names) when no SENSORS match

    for item in director_all_items:
        try:
            if item["type"] != CONTROL4_ENTITY_TYPE or not item.get("id"):
                continue

            item_id = item["id"]
            item_area = item["roomName"]
            item_parent_id = item["parentId"]
            item_proxy = item.get("proxy")

            item_manufacturer = None
            item_device_name = None
            item_model = None

            for parent_item in director_all_items:
                if parent_item.get("id") == item_parent_id:
                    item_manufacturer = parent_item.get("manufacturer")
                    item_device_name = parent_item.get("name")
                    item_model = parent_item.get("model")
                    break

            # Get the item's attrs (not the parent); normalize keys to uppercase to match WS updates
            raw_attrs = await director_get_entry_variables(hass, entry, item_id)
            attrs = {str(k).upper(): v for k, v in raw_attrs.items()}

            for sm in SENSORS:
                if sm.key in attrs and (sm.proxies and item_proxy in sm.proxies):
                    entities.append(
                        Control4AttrSensor(
                            entry_data=entry_data,
                            entry=entry,
                            name=sm.name_suffix,
                            idx=item_id,
                            device_name=item_device_name,
                            device_manufacturer=item_manufacturer,
                            device_model=item_model,
                            device_id=item_parent_id,
                            device_area=item_area,
                            device_attributes=attrs,
                            sensor_map=sm,
                        )
                    )

            # Collect variable names when no SENSORS entry matched (for debug)
            if attrs and len(unmatched_vars_sample) < 3:
                if not any(
                    sm.key in attrs and sm.proxies and item_proxy in sm.proxies for sm in SENSORS
                ):
                    unmatched_vars_sample.append((item_id, str(item.get("name", "")), list(attrs.keys())))

        except Exception:
            _LOGGER.debug("Skipping invalid sensor item: %s", item, exc_info=True)
            continue

    if entities:
        async_add_entities(entities, True)
        _LOGGER.info("Control4 sensor: set up %d entity(ies)", len(entities))
    else:
        _LOGGER.info(
            "Control4 sensor: no entities found (no devices with variables matching SENSORS config: LEVEL, PRESET, CURRENT_POWER, etc.). "
            "Only binary_sensor (e.g. Dynalite triggers) may appear. Enable debug for 'custom_components.control4.sensor' to see variable names per device."
        )
        for item_id, name, var_names in unmatched_vars_sample:
            _LOGGER.debug(
                "id=%s name=%s variable keys: %s (add matching keys to SENSORS if needed)",
                item_id,
                name,
                var_names,
            )


class Control4AttrSensor(Control4Entity, SensorEntity):  # type: ignore[misc]
    """Sensor exposing a Control4 device attribute via WebSocket."""

    _attr_has_entity_name = True
    _attr_should_poll = False 

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        name: str,
        idx: int,
        device_name: str | None,
        device_manufacturer: str | None,
        device_model: str | None,
        device_id: int,
        device_area: str,
        device_attributes: dict,
        sensor_map: _SensorMap,
    ) -> None:
        super().__init__(
            entry_data,
            entry,
            name,
            idx,
            device_name,
            device_manufacturer,
            device_model,
            device_id,
            device_area,
            device_attributes,
        )

        self._sm = sensor_map
        self._attr_unique_id = f"{idx}-{sensor_map.key.lower().lstrip('_')}"
        self._attr_native_unit_of_measurement = sensor_map.unit
        self._attr_device_class = sensor_map.device_class
        self._attr_state_class = sensor_map.state_class
        self._attr_entity_registry_visible_default = False

    async def async_added_to_hass(self) -> None:
        """Subscribe to the existing WebSocket."""
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:  # type: ignore[override]
        return super().available and (self._sm.key in self.extra_state_attributes)

    @property
    def native_value(self):  # type: ignore[override]
        """Retrieve the value from extra_state_attributes (updated by WebSocket)."""
        raw = self.extra_state_attributes.get(self._sm.key)
        if raw is None:
            return None

        if self._sm.unit is not None:
            try:
                val = float(raw)
            except (TypeError, ValueError):
                return None
            if self._sm.value_fn:
                val = self._sm.value_fn(val)
            return val
        # No unit: allow string or number (e.g. Preset name or Level 0-100)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return str(raw)