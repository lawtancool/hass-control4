"""Platform for Control4 energy/power sensors."""
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

from . import Control4Entity, get_items_of_category
from .const import DOMAIN, CONTROL4_ENTITY_TYPE
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "lights"

@dataclass
class _SensorMap:
    key: str
    name_suffix: str
    unit: str | None
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    value_fn: Callable[[Any], Any] | None = None

SENSORS: list[_SensorMap] = [
    _SensorMap(
        key="CURRENT_POWER",
        name_suffix="Power",
        unit="W",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    _SensorMap(
        key="ENERGY_USED_TODAY",
        name_suffix="Energy Today",
        unit="Wh",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,  
    ),
]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    entry_data = hass.data[DOMAIN][entry.entry_id]

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)
    entities: list[Control4AttrSensor] = []

    for item in items_of_category:
        try:
            if item["type"] != CONTROL4_ENTITY_TYPE or not item.get("id"):
                continue

            item_id = item["id"]
            item_name = str(item["name"])
            item_area = item["roomName"]
            item_parent_id = item["parentId"]

            # Récupère les attrs de l'item (pas du parent)
            attrs = await director_get_entry_variables(hass, entry, item_id)

            for sm in SENSORS:
                if sm.key in attrs:
                    entities.append(
                        Control4AttrSensor(
                            entry_data=entry_data,
                            entry=entry,
                            name=f"{item_name} {sm.name_suffix}",
                            idx=item_id,  # Utilise l'ID de l'item
                            device_name=item.get("name"),
                            device_manufacturer=item.get("manufacturer"),
                            device_model=item.get("model"),
                            device_id=item_parent_id,
                            device_area=item_area,
                            device_attributes=attrs,
                            sensor_map=sm,
                        )
                    )

        except Exception:
            _LOGGER.debug("Skipping invalid light item: %s", item, exc_info=True)
            continue

    if entities:
        async_add_entities(entities, True)


class Control4AttrSensor(Control4Entity, SensorEntity):
    """Capteur exposant un attribut de l'équipement Control4 via WebSocket."""

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
        self._attr_unique_id = f"{idx}-{sensor_map.key.lower()}"
        self._attr_native_unit_of_measurement = sensor_map.unit
        self._attr_device_class = sensor_map.device_class
        self._attr_state_class = sensor_map.state_class

    async def async_added_to_hass(self) -> None:
        """S'abonner au WebSocket existant."""
        await super().async_added_to_hass()
        # Le WebSocket est déjà géré par Control4Entity parent
        # Pas besoin d'actions supplémentaires !

    @property
    def available(self) -> bool:
        return super().available and (self._sm.key in self.extra_state_attributes)

    @property
    def native_value(self):
        """Récupère la valeur depuis extra_state_attributes (mis à jour par WebSocket)."""
        raw = self.extra_state_attributes.get(self._sm.key)
        if raw is None:
            return None
        
        try:
            val = float(raw)
        except (TypeError, ValueError):
            return None
            
        if self._sm.value_fn:
            val = self._sm.value_fn(val)
            
        return val

