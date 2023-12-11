"""Platform for Control4 Fan."""
from __future__ import annotations

import logging
from typing import Any

from pyControl4.fan import C4Fan

from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 fans from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)

    entity_list = []

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
            else:
                continue
        except KeyError:
            _LOGGER.exception(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue


        item_attributes = await director_get_entry_variables(hass, entry, item_id)

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
           This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4Fan(self.entry_data[CONF_DIRECTOR], self._idx)
    
    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update for our item id/parent device id."""
        # Message will be False when a Websocket disconnect is detected
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]
            if "fan_state" in data:
                fan_state = data["fan_state"]
                if "current_speed" in fan_state:
                    _LOGGER.debug("Zupdate fan speed %s", str(fan_state))
                    current_speed = fan_state.pop("current_speed")
                    self._extra_state_attributes["CURRENT_SPEED"] = current_speed
            if "fan_setup" in data:
                fan_setup = data["fan_setup"]
                if "preset_speed" in fan_setup:
                    preset_speed = fan_setup.pop("preset_speed")
                    self._extra_state_attributes["PRESET_SPEED"] = preset_speed

        self.schedule_update_ha_state()


    @property
    def percentage_step(self) -> float:
        """Return the step size for percentage."""
        return 25

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        return ranged_value_to_percentage(
            (1, 4), self._extra_state_attributes["CURRENT_SPEED"]
        )

    @property
    def is_on(self):
        """Return whether this fan is on or off."""
        return self._extra_state_attributes["CURRENT_SPEED"] != 0

    @property
    def preset_modes(self):
        """Return a list of available modes for the fan."""
        return list(range(0, 5))

    @property
    def preset_mode(self):
        """Return the current mode of this fan between 0..4."""
        return self._extra_state_attributes["PRESET_SPEED"]

    @property
    def supported_features(self) -> FanEntityFeature:
        """Flag supported features."""
        return FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        c4_fan = self.create_api_object()

        if self._extra_state_attributes["PRESET_SPEED"] != 0:
            await c4_fan.setSpeed(self._extra_state_attributes["PRESET_SPEED"])
        else:
            await c4_fan.setSpeed(1)

    async def async_set_preset_mode(self, preset_mode: int) -> None:
        c4_fan = self.create_api_object()
        await c4_fan.setPreset(preset_mode)

    async def async_set_percentage(self, percentage: int) -> None:
        c4_fan = self.create_api_object()
        speed = percentage_to_ranged_value((1, 4), percentage)
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
