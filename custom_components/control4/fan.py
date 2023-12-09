"""Platform for Control4 Fan."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from pyControl4.error_handling import C4Exception
from pyControl4.fan import C4Fan

from homeassistant.components.fan import (
    ATTR_PERCENTAGE,
    ATTR_PERCENTAGE_STEP,
    ATTR_PRESET_MODE,
    ATTR_PRESET_MODES,
    FanEntity,
    FanEntityFeature,
    FanEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from . import Control4Entity, get_items_of_category, get_items_of_proxy
from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import update_variables_for_config_entry

_LOGGER = logging.getLogger(__name__)

CONTROL4_PROXY = "fan"
CONTROL4_FAN_VARS = ["IS_ON", "FAN_SPEED", "PRESET_SPEED", "PRESET_MODE", "CURRENT_SPEED"]


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 fans from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    scan_interval = entry_data[CONF_SCAN_INTERVAL]
    _LOGGER.debug(
        "Scan interval = %s",
        scan_interval,
    )

    async def async_update_data():
        """Fetch data from Control4 director for fan."""
        try:
            return await update_variables_for_config_entry(
                hass, entry, {*CONTROL4_FAN_VARS}
            )
        except C4Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    fan_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="fan",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    # Fetch initial data so we have data when entities subscribe
    await fan_coordinator.async_refresh()

    items_of_proxy = await get_items_of_proxy(hass, entry, CONTROL4_PROXY)

    entity_list = []
    for item in items_of_proxy:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item['proxy'] == 'fan':
                item_name = item["name"]
                item_id = item["id"]
                item_parent_id = item["parentId"]

                item_manufacturer = None
                item_device_name = None
                item_model = None

                for parent_item in items_of_proxy:
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
                

        if item_id in fan_coordinator.data:
            item_is_fan = True
            item_coordinator = fan_coordinator
        else:
            director = entry_data[CONF_DIRECTOR]
            item_variables = await director.getItemVariables(item_id)
            _LOGGER.warning(
                (
                    "Couldn't get fan state data for %s, skipping setup. Available"
                    " variables from Control4: %s"
                ),
                item_name,
                item_variables,
            )
            continue

        entity_list.append(
            Control4Fan(
                entry_data, item_coordinator, item_name, item_id, item_device_name, item_manufacturer, item_model, item_parent_id,)
        )

    async_add_entities(entity_list, True)


class Control4Fan(Control4Entity, FanEntity):
    """Control4 fan entity."""

    def __init__(
        self,
        entry_data: dict,
        coordinator: DataUpdateCoordinator,
        name: str,
        idx: int,
        device_name: str | None,
        device_manufacturer: str | None,
        device_model: str | None,
        device_id: int,
    ) -> None:
        """Initialize Control4 fan entity."""
        super().__init__(
            entry_data,
            coordinator,
            name,
            idx,
            device_name,
            device_manufacturer,
            device_model,
            device_id,
        )
            #self._attr_color_mode = ColorMode.ONOFF
            #self._attr_supported_color_modes = {ColorMode.ONOFF}

    def _create_api_object(self):
        """Create a pyControl4 device object.

        This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4Fan(self.entry_data[CONF_DIRECTOR], self._idx)

    @property
    def percentage_step(self) -> float:
        """Return the step size for percentage."""
        return 25

    @property
    def percentage(self) -> int | None:
        """Return the current speed as a percentage."""
        return ranged_value_to_percentage((1,4),self.coordinator.data[self._idx]["CURRENT_SPEED"])

    @property
    def is_on(self):
        """Return whether this fan is on or off."""
        return self.coordinator.data[self._idx]["IS_ON"] > 0
    
    @property
    def preset_modes(self):
        """Return a list of available modes for the fan."""
        return list(range(0,5))

    @property
    def preset_mode(self):
        """Return the current mode of this fan between 0..4."""
        return self.coordinator.data[self._idx]["PRESET_SPEED"]

    @property
    def supported_features(self) -> FanEntityFeature:
        """Flag supported features."""
        return FanEntityFeature.PRESET_MODE | FanEntityFeature.SET_SPEED

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the entity on."""
        c4_fan = self._create_api_object()
        if self.coordinator.data[self._idx]["PRESET_SPEED"] != 0:
            await c4_fan.setSpeed(self.coordinator.data[self._idx]["PRESET_SPEED"])
        else:
            await c4_fan.setSpeed(1)

    async def async_set_preset_mode(self, preset_mode: int) -> None:
        c4_fan = self._create_api_object()
        await c4_fan.setPreset(preset_mode)

    async def async_set_percentage(self, percentage: int) -> None:
        c4_fan = self._create_api_object()
        speed = percentage_to_ranged_value((1,4),percentage)
        await c4_fan.setSpeed(speed)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the entity off."""
        c4_fan = self._create_api_object()
        await c4_fan.setSpeed(0)

    async def async_toggle(self, **kwargs: Any) -> None:
        """Toggle the fan."""
        if self.is_on():
            await async_turn_off()
        else:
            await async_turn_on()
