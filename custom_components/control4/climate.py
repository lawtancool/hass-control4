"""Platform for Control4 Climate."""
from __future__ import annotations

# import asyncio
import logging
from typing import Any

# from pyControl4.error_handling import C4Exception

from pyControl4.climate import C4Climate

from homeassistant.components.climate import (
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
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
    CONF_SCAN_INTERVAL,
)


from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util.percentage import (
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)
from . import Control4Entity, get_items_of_category
from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "comfort"
CONTROL4_PROXY = "thermostatV2"

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

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)

    entity_list = []

    for item in items_of_category:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["proxy"] == CONTROL4_PROXY:
                item_name = item["name"]
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
    ) -> None:
        """Initialize Control4 binary sensor entity."""
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
        self._extra_state_attributes["aux_mode_active"] = False

    def create_api_object(self):
        """Create a pyControl4 device object.
        This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4Climate(self.entry_data[CONF_DIRECTOR], self._idx)

    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update for our item id/parent device id."""
        # Message will be False when a Websocket disconnect is detected
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]

            _LOGGER.debug("Climate Event Data Received: %s", message)

            if "hvac_state" in data:
                self._extra_state_attributes["HVAC_STATE"] = data["hvac_state"]

            if "humidity" in data:
                self._extra_state_attributes["HUMIDITY"] = data["humidity"]
            if "setpoint_heat" in data:
                self._extra_state_attributes["HEAT_SETPOINT"] = data["setpoint_heat"]
            if "setpoint_heat_f" in data:
                self._extra_state_attributes["HEAT_SETPOINT_F"] = data[
                    "setpoint_heat_f"
                ]
            if "setpoint_heat_c" in data:
                self._extra_state_attributes["HEAT_SETPOINT_C"] = data[
                    "setpoint_heat_c"
                ]
            if "setpoint_cool" in data:
                self._extra_state_attributes["COOL_SETPOINT"] = data["setpoint_cool"]
            if "setpoint_cool_f" in data:
                self._extra_state_attributes["COOL_SETPOINT_F"] = data[
                    "setpoint_cool_f"
                ]
            if "setpoint_cool_c" in data:
                self._extra_state_attributes["COOL_SETPOINT_C"] = data[
                    "setpoint_cool_c"
                ]
            if "current_temperature" in data:
                self._extra_state_attributes["CURRENT_TEMPERATURE"] = data[
                    "current_temperature"
                ]
            if "temperature" in data:
                self._extra_state_attributes["TEMPERATURE"] = data["temperature"]
            if "current_temperature_f" in data:
                self._extra_state_attributes["CURRENT_TEMPERATURE_F"] = data[
                    "current_temperature_f"
                ]
            if "current_temperature_c" in data:
                self._extra_state_attributes["CURRENT_TEMPERATURE_C"] = data[
                    "current_temperature_c"
                ]
            if "hvac_mode" in data:
                self._extra_state_attributes["HVAC_MODE"] = data["hvac_mode"]
            if "fan_mode" in data:
                self._extra_state_attributes["FAN_MODE"] = data["fan_mode"]
            if "fan_state" in data:
                self._extra_state_attributes["FAN_STATE"] = data["fan_state"]
            await self._data_to_extra_state_attributes(data)

        self.schedule_update_ha_state()

    @property
    def current_humidity(self) -> int | None:
        """Return the current humidity."""
        return self._extra_state_attributes["HUMIDITY"]

    @property
    def aux_mode_active(self) -> bool:
        """Return the current aux mode."""
        return self._extra_state_attributes["aux_mode_active"]

    @property
    def current_temperature(self) -> float:
        """Return the current temperature."""
        return self._extra_state_attributes["TEMPERATURE_F"]

    @property
    def fan_mode(self) -> str | None:
        """Returns the current fan mode."""
        if self._extra_state_attributes["FAN_MODE"] in FAN_MODES:
            return FAN_MODES[self._extra_state_attributes["FAN_MODE"]]
        return None

    @property
    def fan_modes(self) -> list[str] | None:
        """Returns current fan modes supported."""
        return list(FAN_MODES.values())

    @property
    def hvac_action(self) -> str | None:
        """Returns current HVAC action."""
        hvac_state = self._extra_state_attributes["HVAC_STATE"]
        if "Cool" in hvac_state:
            return HVACAction.COOLING
        if "Heat" in hvac_state:
            return HVACAction.HEATING
        return HVACAction.OFF

    @property
    def hvac_mode(self) -> str | None:
        if (
            self._extra_state_attributes["HVAC_MODE"] == ""
            or self._extra_state_attributes["HVAC_MODE"] not in HVAC_MODES
        ):
            return HVACMode.OFF
        return HVAC_MODES[self._extra_state_attributes["HVAC_MODE"]]

    @property
    def hvac_modes(self) -> list(str) | None:
        """Returns current fan mode."""
        active_modes = list()
        c4modes = self._extra_state_attributes["HVAC_MODES_LIST"].split(",")
        # _LOGGER.debug( "c4modes = %s", self.coordinator.data[self._idx]["HVAC_MODES_LIST"],)
        for mode in c4modes:
            # _LOGGER.debug( "a_c4mode = %s", mode,)
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
        return "Emergency" in self._extra_state_attributes["HVAC_MODE"]

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature currently set to be reached."""
        if self.hvac_mode == HVACMode.HEAT:
            if "HEAT_SETPOINT_F" in self._extra_state_attributes:
                return self._extra_state_attributes["HEAT_SETPOINT_F"]
        if self.hvac_mode == HVACMode.COOL:
            if "COOL_SETPOINT_F" in self._extra_state_attributes:
                return self._extra_state_attributes["COOL_SETPOINT_F"]
        return None

    @property
    def target_temperature_high(self) -> float | None:
        """Return the upper bound target temperature."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._extra_state_attributes["COOL_SETPOINT_F"]

    @property
    def target_temperature_low(self) -> float | None:
        """Return the lower bound target temperature."""
        if self.hvac_mode != HVACMode.HEAT_COOL:
            return None
        return self._extra_state_attributes["HEAT_SETPOINT_F"]

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement used by the platform."""
        if self._extra_state_attributes["SCALE"] == "F":
            return UnitOfTemperature.FAHRENHEIT
        else:
            return UnitOfTemperature.CELSIUS

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Flag supported features."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        )
        if "Emergency" in self._extra_state_attributes["HVAC_MODES_LIST"]:
            features = features | ClimateEntityFeature.AUX_HEAT
        #    _LOGGER.debug( "Emergency Found: %s",
        #        self._extra_state_attributes["HVAC_MODES_LIST"],
        # )
        return features

    async def async_set_hvac_mode(self, hvac_mode) -> None:
        """Set the hvac mode."""
        c4_climate = self.create_api_object()

        #
        _LOGGER.debug(
            "set hvac mode: %s",
            hvac_mode,
        )
        if hvac_mode == HVACMode.HEAT:
            if self.aux_mode_active:
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
                "Request for unsupported hvac mode received:: %s",
                hvac_mode,
            )

    #    async def async_set_humidity(self, humidity) -> None:
    #        """Set new target humidity."""
    #        c4_climate = self.create_api_object()
    #        await c4_climate.setHumidity(humidity)

    async def async_set_temperature(self, **kwargs) -> None:
        """Set new target temperature."""
        c4_climate = self.create_api_object()
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
            raise UpdateFailed(
                f"Error setting {self.entity_id} temperature to {kwargs}: {err}"
            ) from err

    async def async_turn_aux_heat_off(self) -> None:
        """Turn auxiliary heater off."""
        self._extra_state_attributes["aux_mode_active"] = False

    async def async_turn_aux_heat_on(self) -> None:
        """Turn auxiliary heater on."""
        self._extra_state_attributes["aux_mode_active"] = True
