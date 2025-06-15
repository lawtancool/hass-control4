"""Platform for Control4 Fan."""
from __future__ import annotations

import logging

from .pyControl4.fan import C4Fan

import json
from typing import Any

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)


from . import Control4Entity, get_items_of_category
from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_PROXY = "fan"
CONTROL4_CATEGORY = "lights"

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 fans from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    director = entry_data[CONF_DIRECTOR]
    
    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)

    entity_list = []
    setup_attributes = {}

    for item in items_of_category:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["proxy"] == CONTROL4_PROXY:
                item_name = str(item["name"])
                item_id = item["id"]
                item_area = item["roomName"]
                item_parent_id = item["parentId"]

                item_manufacturer = None
                item_device_name = None
                item_model = None

                for parent_item in items_of_category:
                    if parent_item["id"] == item_parent_id:
                        item_manufacturer = parent_item["manufacturer"]
                        item_device_name = parent_item["name"]
                        item_model = parent_item["model"]

                item_setup_info = await director.getItemSetup(item_id)
                item_setup_info = json.loads(item_setup_info)
                _LOGGER.debug("Fan Setup: %s",str(item_setup_info))
                if 'fan_setup' in item_setup_info:
                    setup_attributes = item_setup_info['fan_setup']
            else:
                continue
        except KeyError:
            _LOGGER.exception(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue


        item_attributes = await director_get_entry_variables(hass, entry, item_id) | setup_attributes
        _LOGGER.debug("Fan Attributes: %s",str(item_attributes))

        entity_list.append(
            Control4Fan(
                entry_data,
                entry,
                item_name,
                item_id,
                item_device_name,
                item_manufacturer,
                item_model,
                item_parent_id,
                item_area,
                item_attributes,
            )
        )

    async_add_entities(entity_list, True)


class Control4Fan(Control4Entity, FanEntity):
    """Control4 fan entity."""

    def create_api_object(self):
        """Create a pyControl4 device object.
           This exists so the director token used is always the
           latest one, without needing to re-init the entire entity.
        """
        return C4Fan(self.entry_data[CONF_DIRECTOR], self._idx)
    
    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update for our item id/parent device id."""
        # Message will be False when a Websocket disconnect is detected
        _LOGGER.debug("Turn ON Fan Attributes: %s",str(message))
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]
            if "fan_state" in data:
                self._extra_state_attributes["current_speed"] = data["fan_state"].pop("current_speed")
                self._extra_state_attributes["directions"] = data["fan_state"].pop("is_reversed")
                await self._data_to_extra_state_attributes(data["fan_state"])
            else:
                _LOGGER.error("Unknown fan state data: %s", data)
                await self._data_to_extra_state_attributes(data)

        _LOGGER.debug("Message for device %s", device)
        self.async_write_ha_state()

    @property
    def percentage_step(self) -> float:
        """Return the step size for percentage."""
        return 100/self._extra_state_attributes["speeds_count"]

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        if "current_speed" in self._extra_state_attributes:
            return ranged_value_to_percentage(
                (1, self._extra_state_attributes["speeds_count"]), 
                 self._extra_state_attributes["current_speed"]
            )
        return ranged_value_to_percentage(
            (1, self._extra_state_attributes["speeds_count"]), 
              self._extra_state_attributes["CURRENT_SPEED"]
        )

    @property
    def is_on(self):
        """Return whether this fan is on or off."""
        for key in ("current_speed", "CURRENT_SPEED"):
            speed = self._extra_state_attributes.get(key)
            if speed is not None:
                return speed != 0
        return False  # If both are None, assume off


    @property
    def preset_modes(self):
        """Return a list of available modes for the fan."""
        return list(range(0, self._extra_state_attributes["speeds_count"]+1))

    @property
    def preset_mode(self):
        """Return the current peset mode of this fan. """
        return self._extra_state_attributes["preset_speed"]

    @property
    def supported_features(self) -> FanEntityFeature:
        """Flag supported features."""
        return FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF


    async def async_turn_on(self, speed: Optional[str] = None, percentage: Optional[int] = None, preset_mode: Optional[str] = None, **kwargs: Any) -> None:
        """Turn the entity on."""
        _LOGGER.debug("Turn ON Fan Attributes: %s",str(self._extra_state_attributes))

        c4_fan = self.create_api_object()

        if self._extra_state_attributes["preset_speed"] != 0:
            await c4_fan.setSpeed(self._extra_state_attributes["preset_speed"])
        else:
            await c4_fan.setSpeed(1)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode, the speed the fan comes on to."""
        c4_fan = self.create_api_object()
        await c4_fan.setPreset(preset_mode)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set a percentage speed for the fan comes on to."""
        c4_fan = self.create_api_object()
        speed = percentage_to_ranged_value((1, self._extra_state_attributes["speeds_count"]), percentage)
        await c4_fan.setSpeed(speed)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        c4_fan = self.create_api_object()
        await c4_fan.setSpeed(0)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the fan."""
        if self.is_on():
            await self.async_turn_off()
        else:
            await self.async_turn_on()


