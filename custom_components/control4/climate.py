"""Platform for Control4 Climate."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
from typing import Any

from pyControl4.error_handling import C4Exception
from pyControl4.climate import C4Climate

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ATTR_HVAC_MODE,
    ATTR_CURRENT_TEMPERATURE,
    FAN_AUTO,
    FAN_DIFFUSE,
    FAN_ON,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE, 
    UnitOfTemperature,
    PRECISION_HALVES,
    PRECISION_WHOLE,
    CONF_SCAN_INTERVAL
    )


from homeassistant.config_entries import ConfigEntry
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

CONTROL4_PROXY = "thermostatV2"
CONTROL4_CLIMATE_VARS = ["HUMIDITY","TEMPERATURE_F","TEMPERATURE_C",
                         "HVAC_MODE","FAN_MODE","FAN_STATE",
                         "FAN_MODES_LIST","HVAC_MODES_LIST","SCALE",
                         "HVAC_STATE","HEAT_SETPOINT_F","COOL_SETPOINT_F"]

CONTROL4_HVAC_MODE_OFF = "Off"
CONTROL4_HVAC_MODE_HEAT = "Heat"
CONTROL4_HVAC_MODE_COOL = "Cool"
CONTROL4_HVAC_MODE_HEAT_COOL = "Auto"
CONTROL4_HVAC_MODE_AUX_HEAT = "Emergency Heat"


CONTROL4_FAN_MODE_ON = "On"
CONTROL4_FAN_MODE_AUTO = "Auto"
CONTROL4_FAN_MODE_DIFFUSE = "Circulate"
MIN_TEMP_RANGE = 2 

CONTROL4_HVAC_MODES = {
    HVACMode.OFF: CONTROL4_HVAC_MODE_OFF,
    HVACMode.HEAT: CONTROL4_HVAC_MODE_HEAT,
    HVACMode.COOL: CONTROL4_HVAC_MODE_COOL,
    HVACMode.HEAT_COOL: CONTROL4_HVAC_MODE_HEAT_COOL,
}

HVAC_MODES = {
    CONTROL4_HVAC_MODE_OFF: HVACMode.OFF,
    CONTROL4_HVAC_MODE_HEAT: HVACMode.HEAT,
    CONTROL4_HVAC_MODE_AUX_HEAT: HVACMode.HEAT,
    CONTROL4_HVAC_MODE_COOL: HVACMode.COOL,
    CONTROL4_HVAC_MODE_HEAT_COOL: HVACMode.HEAT_COOL,
}

CONTROL4_FAN_MODES = {
    FAN_ON: CONTROL4_FAN_MODE_ON,
    FAN_AUTO: CONTROL4_FAN_MODE_AUTO,
    FAN_DIFFUSE: CONTROL4_FAN_MODE_DIFFUSE,
}

FAN_MODES = {
    CONTROL4_FAN_MODE_ON: FAN_ON,
    CONTROL4_FAN_MODE_AUTO: FAN_AUTO,
    CONTROL4_FAN_MODE_DIFFUSE: FAN_DIFFUSE,
}



async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 climate thermostats from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    scan_interval = entry_data[CONF_SCAN_INTERVAL]
    _LOGGER.debug(
        "Scan interval = %s",
        scan_interval,
    )

    async def async_update_data():
        """Fetch data from Control4 director for climate."""
        try:
            return await update_variables_for_config_entry(
                hass, entry, {*CONTROL4_CLIMATE_VARS}
            )
        except C4Exception as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    climate_coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="climate",
        update_method=async_update_data,
        update_interval=timedelta(seconds=scan_interval),
    )

    # Fetch initial data so we have data when entities subscribe
    await climate_coordinator.async_refresh()

    items_of_proxy = await get_items_of_proxy(hass, entry, CONTROL4_PROXY)

    entity_list = []
    for item in items_of_proxy:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item['proxy'] == 'thermostatV2':
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
                

        if item_id in climate_coordinator.data:
            item_is_climate = True
            item_coordinator = climate_coordinator
        else:
            director = entry_data[CONF_DIRECTOR]
            item_variables = await director.getItemVariables(item_id)
            _LOGGER.warning(
                (
                    "Couldn't get climate state data for %s, skipping setup. Available"
                    " variables from Control4: %s"
                ),
                item_name,
                item_variables,
            )
            continue

        entity_list.append(
            Control4Climate(
                entry_data, item_coordinator, item_name, item_id, item_device_name, item_manufacturer, item_model, item_parent_id,)
        )

    async_add_entities(entity_list, True)


class Control4Climate(Control4Entity, ClimateEntity):
    """Control4 climate entity."""

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
        """Initialize Control4 climate entity."""
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
        self._aux_mode_active = False

    def _create_api_object(self):
        """Create a pyControl4 device object.

        This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4Climate(self.entry_data[CONF_DIRECTOR], self._idx)


    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        return self.coordinator.data[self._idx]["HUMIDITY"]
    
    @property
    def aux_mode_active(self) -> bool:
        """Return the current aux mode."""
        return self._aux_mode_active
    
    @property
    def current_temperature(self) -> float:
        """Return the current temperature."""
        return self.coordinator.data[self._idx]["TEMPERATURE_F"]

    @property
    def fan_mode(self) -> str | None:
        """Returns the current fan mode."""
        if self.coordinator.data[self._idx]["FAN_MODE"] in FAN_MODES:
           return FAN_MODES[self.coordinator.data[self._idx]["FAN_MODE"]]
        return None
    
    @property
    def fan_modes(self) -> list[str] | None:
        """Returns current fan modes supported."""
        return list(FAN_MODES.values())
    
    @property
    def hvac_action(self) -> str | None:
        """Returns current HVAC action."""
        hvac_state = self.coordinator.data[self._idx]["HVAC_STATE"]
        if "Cool" in hvac_state:
            return HVACAction.COOLING
        if "Heat" in hvac_state:
            return HVACAction.HEATING
        return HVACAction.OFF

    @property
    def hvac_mode(self) -> str | None:
        if self.coordinator.data[self._idx]["HVAC_MODE"] == '' or self.coordinator.data[self._idx]["HVAC_MODE"] not in HVAC_MODES:
            return HVACMode.OFF
        return HVAC_MODES[self.coordinator.data[self._idx]["HVAC_MODE"]]
    
    @property
    def hvac_modes(self) -> list(str) | None:
        """Returns current fan mode."""
        active_modes = list() 
        c4modes = self.coordinator.data[self._idx]["HVAC_MODES_LIST"].split(",")
        #_LOGGER.debug( "c4modes = %s", self.coordinator.data[self._idx]["HVAC_MODES_LIST"],)
        for mode in c4modes:
           #_LOGGER.debug( "a_c4mode = %s", mode,)
           if mode in HVAC_MODES and HVAC_MODES[mode] not in active_modes:
              active_modes.append(HVAC_MODES[mode])
        if len(active_modes) == 0:
            active_modes.append(HVACMode.OFF)
        return active_modes 

    @property
    def is_aux_heat(self) -> bool | None:
        """Return true if aux heater is active.
        Requires ClimateEntityFeature.AUX_HEAT.
        """
        return "Emergency" in self.coordinator.data[self._idx]["HVAC_MODE"]

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature currently set to be reached."""
        if self.hvac_mode == HVACMode.HEAT:
            return self.coordinator.data[self._idx]["HEAT_SETPOINT_F"]
        if self.hvac_mode == HVACMode.COOL:
            return self.coordinator.data[self._idx]["COOL_SETPOINT_F"]
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the upper bound target temperature."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self.coordinator.data[self._idx]["COOL_SETPOINT_F"]

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lower bound target temperature."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self.coordinator.data[self._idx]["HEAT_SETPOINT_F"]
    
    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if self.coordinator.data[self._idx]["SCALE"] == "F":
            return UnitOfTemperature.FAHRENHEIT
        else:
            return UnitOfTemperature.CELSIUS

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Flag supported features."""
        features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        if "Emergency" in self.coordinator.data[self._idx]["HVAC_MODES_LIST"]:
            features = features | ClimateEntityFeature.AUX_HEAT
        #    _LOGGER.debug( "Emergency Found: %s",
        #        self.coordinator.data[self._idx]["HVAC_MODES_LIST"],
        # )
        return features

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set the hvac mode."""
        c4_climate = self._create_api_object()

        #  
        _LOGGER.debug( "set hvac mode: %s", hvac_mode,
         )
        if hvac_mode == HVACMode.HEAT:
            if self.aux_mode_active:
                _LOGGER.debug( "set hvac mode with aux: %s", hvac_mode,
                )
                await c4_climate.setHvacMode(CONTROL4_HVAC_MODE_AUX_HEAT)
            else:         
                await c4_climate.setHvacMode(CONTROL4_HVAC_MODE_HEAT)
        else:
            if hvac_mode in CONTROL4_HVAC_MODES:
                await c4_climate.setHvacMode(CONTROL4_HVAC_MODES[hvac_mode])
            else:
                _LOGGER.exception(
                    "Request for unsupported hvac mode received:: %s",
                    hvac_mode,
                )

    async def async_set_fan_mode(self, fan_mode) -> None:
        """Set new target fan mode."""
        c4_climate = self._create_api_object()
        if fan_mode in CONTROL4_FAN_MODES:
            await c4_climate.setFanMode(CONTROL4_FAN_MODES[fan_mode])
        else:
            _LOGGER.exception(
                "Request for unsupported hvac mode received:: %s",
                hvac_mode,
            )

#    async def async_set_humidity(self, humidity) -> None:
#        """Set new target humidity."""
#        c4_climate = self._create_api_object()
#        await c4_climate.setHumidity(humidity)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        c4_climate = self._create_api_object()
        low_temp = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high_temp = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp = kwargs.get(ATTR_TEMPERATURE)
        try:
            if self.hvac_mode == HVACMode.HEAT_COOL:
                if low_temp and high_temp:
                    if high_temp - low_temp < MIN_TEMP_RANGE:
                        # Ensure there is a minimum gap from the new temp. Pick
                        # the temp that is not changing as the one to move.
                        if abs(high_temp - self.target_temperature_high) < 0.01:
                            high_temp = low_temp + MIN_TEMP_RANGE
                        else:
                            low_temp = high_temp - MIN_TEMP_RANGE
                    await c4_climate.setHeatSetpoint(low_temp)
                    await c4_climate.setCoolSetpoint(high_temp)
            elif self.hvac_mode == HVACMode.COOL and temp:
                await c4_climate.setCoolSetpoint(temp)
            elif self.hvac_mode == HVACMode.HEAT and temp:
                await c4_climate.setHeatSetpoint(temp)
        except C4Exception as err:
            raise UpdateFailed(f"Error setting {self.entity_id} temperature to {kwargs}: {err}") from err

  
    async def async_turn_aux_heat_off(self) -> None:
        """Turn auxiliary heater off."""
        self._aux_mode_active = False

    async def async_turn_aux_heat_on(self) -> None:
        """Turn auxiliary heater on."""
        self._aux_mode_active = True
