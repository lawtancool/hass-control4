"""Platform for Control4 Climate."""

from __future__ import annotations

import json
import logging


from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    FAN_AUTO,
    FAN_DIFFUSE,
    FAN_ON,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)

from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature, PRECISION_WHOLE

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pyControl4.climate import C4Climate

from . import Control4Entity, get_items_of_category
from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "comfort"
CONTROL4_PROXY = {"control4_thermostat_proxy", "thermostatV2"}

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

# Attribute name constants
ATTR_HUMIDITY = "HUMIDITY"
ATTR_TEMPERATURE_F = "TEMPERATURE_F"
ATTR_TEMPERATURE_C = "TEMPERATURE_C"
ATTR_FAN_MODE = "FAN_MODE"
ATTR_FAN_STATE = "FAN_STATE"
ATTR_FAN_MODES_LIST = "FAN_MODES_LIST"
ATTR_HVAC_STATE = "HVAC_STATE"
ATTR_HVAC_MODE = "HVAC_MODE"
ATTR_HVAC_MODES_LIST = "HVAC_MODES_LIST"
ATTR_HOLD_MODE = "HOLD_MODE"
ATTR_HOLD_MODES_LIST = "HOLD_MODES_LIST"
ATTR_SETPOINT_HEAT_F = "SETPOINT_HEAT_F"
ATTR_HEAT_SETPOINT_F = "HEAT_SETPOINT_F"
ATTR_SETPOINT_HEAT_C = "SETPOINT_HEAT_C"
ATTR_HEAT_SETPOINT_C = "HEAT_SETPOINT_C"
ATTR_SETPOINT_COOL_F = "SETPOINT_COOL_F"
ATTR_COOL_SETPOINT_F = "COOL_SETPOINT_F"
ATTR_SETPOINT_COOL_C = "SETPOINT_COOL_C"
ATTR_COOL_SETPOINT_C = "COOL_SETPOINT_C"
ATTR_SCALE = "SCALE"
SETUP_HAS_HUMIDITY = "has_humidity"
SETUP_CURRENT_TEMP_RES_F = "current_temperature_resolution_f"
SETUP_CURRENT_TEMP_RES_C = "current_temperature_resolution_c"
SETUP_SETPOINT_HEAT_RES_F = "setpoint_heat_resolution_f"
SETUP_SETPOINT_COOL_RES_F = "setpoint_cool_resolution_f"
SETUP_SETPOINT_HEAT_RES_C = "setpoint_heat_resolution_c"
SETUP_SETPOINT_COOL_RES_C = "setpoint_cool_resolution_c"
SETUP_SETPOINT_DEADBAND_F = "setpoint_heatcool_deadband_f"
SETUP_SETPOINT_DEADBAND_C = "setpoint_heatcool_deadband_c"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 climate thermostats from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    director = entry_data[CONF_DIRECTOR]

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)

    entity_list = []

    for item in items_of_category:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["proxy"] in CONTROL4_PROXY:
                item_name = item["name"]
                _LOGGER.debug("Climate Setup Name: %s", str(item_name))
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
                _LOGGER.debug("Climate Setup: %s", str(item_setup_info))
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
            Control4Climate(
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
                item_setup_info.get("thermostat_setup"),
            )
        )

    async_add_entities(entity_list, True)


class Control4Climate(Control4Entity, ClimateEntity):
    """Control4 climate entity."""

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
        thermostat_setup: dict | None,
    ) -> None:
        """Initialize Control4 climate entity."""
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
        if isinstance(thermostat_setup, dict):
            self._thermostat_setup = thermostat_setup
        else:
            self._thermostat_setup = {}
        self._aux_heat_active = False

    def create_api_object(self):
        """Create a pyControl4 device object.
        This exists so the director token used is always the
        latest one, without needing to re-init the entire entity.
        """
        return C4Climate(self.entry_data[CONF_DIRECTOR], self._idx)

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        if self._thermostat_setup.get(SETUP_HAS_HUMIDITY, False) is False:
            return None
        return self._extra_state_attributes.get(ATTR_HUMIDITY)

    @property
    def current_temperature(self) -> float:
        """Return the current temperature."""
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            return self._extra_state_attributes.get(ATTR_TEMPERATURE_F)
        return self._extra_state_attributes.get(ATTR_TEMPERATURE_C)

    @property
    def fan_mode(self) -> str | None:
        """Returns the current fan mode."""
        fan_mode = self._extra_state_attributes.get(ATTR_FAN_MODE)
        if fan_mode in FAN_MODES:
            return FAN_MODES[fan_mode]
        return None

    @property
    def fan_modes(self) -> list[str] | None:
        """Returns current fan modes supported."""
        fan_modes = self._extra_state_attributes.get(ATTR_FAN_MODES_LIST)
        if fan_modes:
            control4_fan_modes = fan_modes.split(",")
            # Only include mapped Home Assistant fan modes
            return [FAN_MODES[x] for x in control4_fan_modes if x in FAN_MODES]
        return list(FAN_MODES.values())

    @property
    def preset_modes(self) -> list[str] | None:
        """Return the list of available preset modes."""
        preset_modes = self._extra_state_attributes.get(ATTR_HOLD_MODES_LIST)
        if preset_modes:
            return preset_modes.split(",")
        return None

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        return self._extra_state_attributes.get(ATTR_HOLD_MODE)

    @property
    def hvac_action(self) -> str | None:
        """Returns current HVAC action."""
        hvac_state = self._extra_state_attributes.get(ATTR_HVAC_STATE, "")
        if "Cool" in hvac_state:
            return HVACAction.COOLING
        if "Heat" in hvac_state:
            return HVACAction.HEATING
        fan_state = self._extra_state_attributes.get(ATTR_FAN_STATE, "")
        if "on" in fan_state.lower():
            return HVACAction.FAN
        return HVACAction.OFF

    @property
    def hvac_mode(self) -> str | None:
        """Return current HVAC Mode."""
        hvac_mode = self._extra_state_attributes.get(ATTR_HVAC_MODE, "")
        if hvac_mode == "" or hvac_mode not in HVAC_MODES:
            return HVACMode.OFF
        return HVAC_MODES[hvac_mode]

    @property
    def hvac_modes(self) -> list[str] | None:
        """Returns HVAC modes."""
        active_modes = []
        c4modes_str = self._extra_state_attributes.get(ATTR_HVAC_MODES_LIST, "")
        c4modes = c4modes_str.split(",") if c4modes_str else []
        _LOGGER.debug("c4modes = %s", c4modes_str)
        for mode in c4modes:
            _LOGGER.debug("a_c4mode = %s", mode)
            if mode in HVAC_MODES and HVAC_MODES[mode] not in active_modes:
                active_modes.append(HVAC_MODES[mode])
        if len(active_modes) == 0:
            active_modes.append(HVACMode.OFF)
        return active_modes

    def _get_heat_setpoint(self) -> float | None:
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            if ATTR_SETPOINT_HEAT_F in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_SETPOINT_HEAT_F)
            if ATTR_HEAT_SETPOINT_F in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_HEAT_SETPOINT_F)
        else:
            if ATTR_SETPOINT_HEAT_C in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_SETPOINT_HEAT_C)
            if ATTR_HEAT_SETPOINT_C in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_HEAT_SETPOINT_C)
        return None

    def _get_cool_setpoint(self) -> float | None:
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            if ATTR_SETPOINT_COOL_F in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_SETPOINT_COOL_F)
            if ATTR_COOL_SETPOINT_F in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_COOL_SETPOINT_F)
        else:
            if ATTR_SETPOINT_COOL_C in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_SETPOINT_COOL_C)
            if ATTR_COOL_SETPOINT_C in self._extra_state_attributes:
                return self._extra_state_attributes.get(ATTR_COOL_SETPOINT_C)
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature currently set to be reached."""
        if self.hvac_mode == HVACMode.HEAT:
            return self._get_heat_setpoint()
        if self.hvac_mode == HVACMode.COOL:
            return self._get_cool_setpoint()
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the upper bound target temperature."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._get_cool_setpoint()

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lower bound target temperature."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._get_heat_setpoint()

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        scale = self._extra_state_attributes.get(ATTR_SCALE, "")
        if "f" in scale.lower():
            return UnitOfTemperature.FAHRENHEIT
        return UnitOfTemperature.CELSIUS

    @property
    def precision(self) -> float:
        if isinstance(self._thermostat_setup, dict):
            if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
                res = self._thermostat_setup.get(SETUP_CURRENT_TEMP_RES_F)
                if res is not None:
                    return res
            if self.temperature_unit == UnitOfTemperature.CELSIUS:
                res = self._thermostat_setup.get(SETUP_CURRENT_TEMP_RES_C)
                if res is not None:
                    return res
        return PRECISION_WHOLE

    @property
    def target_temperature_step(self) -> float:
        if isinstance(self._thermostat_setup, dict):
            if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
                res = self._thermostat_setup.get(
                    SETUP_SETPOINT_HEAT_RES_F
                ) or self._thermostat_setup.get(SETUP_SETPOINT_COOL_RES_F)
                if res is not None:
                    return res
            if self.temperature_unit == UnitOfTemperature.CELSIUS:
                res = self._thermostat_setup.get(
                    SETUP_SETPOINT_HEAT_RES_C
                ) or self._thermostat_setup.get(SETUP_SETPOINT_COOL_RES_C)
                if res is not None:
                    return res
        return PRECISION_WHOLE

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Flag supported features."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
            | ClimateEntityFeature.PRESET_MODE
        )
        return features

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set the hvac mode."""
        c4_climate = self.create_api_object()

        _LOGGER.debug(
            "set new hvac mode: %s",
            hvac_mode,
        )
        if hvac_mode == HVACMode.HEAT:
            if self._aux_heat_active:
                _LOGGER.debug(
                    "set hvac mode with aux: %s",
                    hvac_mode,
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
        c4_climate = self.create_api_object()
        if fan_mode in CONTROL4_FAN_MODES:
            await c4_climate.setFanMode(CONTROL4_FAN_MODES[fan_mode])
        else:
            _LOGGER.exception(
                "Request for unsupported fan mode received:: %s",
                fan_mode,
            )

    async def async_set_preset_mode(self, preset_mode) -> None:
        """Set new target preset mode."""
        c4_climate = self.create_api_object()
        await c4_climate.setHoldMode(preset_mode)

    async def async_set_humidity(self, humidity) -> None:
        """Set new target humidity."""
        c4_climate = self.create_api_object()
        await c4_climate.setHumidity(humidity)

    async def _set_cool_setpoint(self, temp) -> None:
        c4_climate = self.create_api_object()
        if self.target_temperature_step >= 1:
            temp = int(temp)
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            await c4_climate.setCoolSetpointF(temp)
        else:
            await c4_climate.setCoolSetpointC(temp)

    async def _set_heat_setpoint(self, temp) -> None:
        c4_climate = self.create_api_object()
        if self.target_temperature_step >= 1:
            temp = int(temp)
        if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
            await c4_climate.setHeatSetpointF(temp)
        else:
            await c4_climate.setHeatSetpointC(temp)

    def _get_setpoint_deadband(self) -> float:
        if isinstance(self._thermostat_setup, dict):
            if self.temperature_unit == UnitOfTemperature.FAHRENHEIT:
                res = self._thermostat_setup.get(SETUP_SETPOINT_DEADBAND_F)
                if res is not None:
                    return res
            if self.temperature_unit == UnitOfTemperature.CELSIUS:
                res = self._thermostat_setup.get(SETUP_SETPOINT_DEADBAND_C)
                if res is not None:
                    return res
        return MIN_TEMP_RANGE

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        low_temp = kwargs.get(ATTR_TARGET_TEMP_LOW)
        high_temp = kwargs.get(ATTR_TARGET_TEMP_HIGH)
        temp = kwargs.get(ATTR_TEMPERATURE)
        if self.hvac_mode == HVACMode.HEAT_COOL:
            if low_temp and high_temp:
                if high_temp - low_temp < self._get_setpoint_deadband():
                    # Ensure there is a minimum gap from the new temp. Pick
                    # the temp that is not changing as the one to move.
                    if abs(high_temp - self.target_temperature_high) < 0.01:
                        high_temp = low_temp + self._get_setpoint_deadband()
                    else:
                        low_temp = high_temp - self._get_setpoint_deadband()
                await self._set_heat_setpoint(low_temp)
                await self._set_cool_setpoint(high_temp)
        elif self.hvac_mode == HVACMode.COOL and temp:
            await self._set_cool_setpoint(temp)
        elif self.hvac_mode == HVACMode.HEAT and temp:
            await self._set_heat_setpoint(temp)

    async def async_turn_aux_heat_on(self) -> None:
        """Turn auxiliary heater on."""
        self._aux_heat_active = True
        if self.hvac_mode == HVACMode.HEAT:
            await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_aux_heat_off(self) -> None:
        """Turn auxiliary heater off."""
        self._aux_heat_active = False
        if self.hvac_mode == HVACMode.HEAT:
            await self.async_set_hvac_mode(HVACMode.HEAT)
