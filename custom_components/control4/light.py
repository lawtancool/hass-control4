"""Platform for Control4 Lights."""
from __future__ import annotations
from typing import Any

import json
import logging

from pyControl4.light import C4Light

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ATTR_XY_COLOR,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_EFFECT,
    LightEntity,
    LightEntityFeature,
    ColorMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import value_to_brightness, brightness_to_value

from . import Control4Entity, get_items_of_category
from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import (
    director_get_entry_variables,
    director_get_multiple_entries_variables,
)

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "lights"
CONTROL4_BRIGHTNESS_SCALE = (1, 100)
CONTROL4_COLOR_MODE_CCT = 1
CONTROL4_COLOR_MODE_XY = 0

async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 lights from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)

    valid_items = []
    for item in items_of_category:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["id"] and item["proxy"] != "fan":
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

                valid_items.append(
                    {
                        "item_name": item_name,
                        "item_id": item_id,
                        "item_area": item_area,
                        "item_parent_id": item_parent_id,
                        "item_manufacturer": item_manufacturer,
                        "item_device_name": item_device_name,
                        "item_model": item_model,
                    }
                )
            else:
                continue
        except KeyError:
            _LOGGER.exception(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue

    item_ids = [item_info["item_id"] for item_info in valid_items]
    variables_map = await director_get_multiple_entries_variables(
        hass, entry, item_ids
    )

    entity_list = []
    for item_info in valid_items:
        item_attributes = variables_map.get(item_info["item_id"], {})
        entity_list.append(
            Control4Light(
                entry_data,
                entry,
                item_info["item_name"],
                item_info["item_id"],
                item_info["item_device_name"],
                item_info["item_manufacturer"],
                item_info["item_model"],
                item_info["item_parent_id"],
                item_info["item_area"],
                item_attributes,
            )
        )

    async_add_entities(entity_list, True)


class Control4Light(Control4Entity, LightEntity):  # type: ignore[misc]
    """Control4 light entity."""

    def __init__(
        self,
        entry_data,
        entry,
        name,
        idx,
        device_name,
        device_manufacturer,
        device_model,
        device_parent_id,
        device_area,
        device_attributes,
    ) -> None:
        super().__init__(
            entry_data,
            entry,
            name,
            idx,
            device_name,
            device_manufacturer,
            device_model,
            device_parent_id,
            device_area,
            device_attributes,
        )

        # Defaults
        self._supports_color: bool = False
        self._supports_ct: bool = False
        self._ct_min: int | None = None
        self._ct_max: int | None = None
        self._rate_min: int | None = None
        self._rate_max: int | None = None
        self._effects_by_name: dict[str, dict[str, Any]] = {}
        self._current_effect: str | None = None
        
        self._attr_supported_color_modes = {ColorMode.BRIGHTNESS} if self._is_dimmer else {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.BRIGHTNESS if self._is_dimmer else ColorMode.ONOFF
        self._attr_min_color_temp_kelvin = None
        self._attr_max_color_temp_kelvin = None


    def create_api_object(self):
        """Create a pyControl4 device object.

        This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4Light(self.entry_data[CONF_DIRECTOR], self._idx)

    
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        director = self.entry_data.get(CONF_DIRECTOR)
        if not director:
            return

        try:
            resp = await director.get_item_setup(self._idx)

            setup = resp.get("setup", resp) if isinstance(resp, dict) else {}

            if isinstance(setup, str):
                setup = json.loads(setup)

            self._supports_color = bool(setup.get("supports_color"))
            self._supports_ct = bool(setup.get("supports_color_correlated_temperature"))

            colors = setup.get("colors") or {}
            if self._supports_ct:
                self._ct_min = (colors.get("color_correlated_temperature_min") or None)
                self._ct_max = (colors.get("color_correlated_temperature_max") or None)
                
                ct_min = self._ct_min
                ct_max = self._ct_max
                if ct_min is not None:
                    self._attr_min_color_temp_kelvin = int(ct_min)
                if ct_max is not None:
                    self._attr_max_color_temp_kelvin = int(ct_max)

            self._rate_min = colors.get("color_rate_min")
            self._rate_max = colors.get("color_rate_max")

            # presets
            for pr in colors.get("color") or []:
                name = pr.get("name")
                if name:
                    self._effects_by_name[name] = pr

            # calculate supported_color_modes now that setup is parsed
            modes = set()
            if self._is_dimmer and not self._supports_color:
                modes.add(ColorMode.BRIGHTNESS)
            if self._supports_color:
                modes.add(ColorMode.XY)
            if self._supports_ct:
                modes.add(ColorMode.COLOR_TEMP)
            if not modes:
                modes = {ColorMode.ONOFF}
            self._attr_supported_color_modes = modes

            # choose initial color_mode
            if ColorMode.XY in modes:
                self._attr_color_mode = ColorMode.XY
            elif ColorMode.COLOR_TEMP in modes:
                self._attr_color_mode = ColorMode.COLOR_TEMP
            elif ColorMode.BRIGHTNESS in modes:
                self._attr_color_mode = ColorMode.BRIGHTNESS
            else:
                self._attr_color_mode = ColorMode.ONOFF

            _LOGGER.debug("Parsed setup for %s: supports_color=%s supports_ct=%s modes=%s",
                        self._idx, self._supports_color, self._supports_ct, self._attr_supported_color_modes)

        except Exception as exc:
            _LOGGER.debug("get_item_setup failed for %s: %s", self._idx, exc)

        self.async_write_ha_state()

    # -----------------------
    # Properties
    # -----------------------
    @property
    def is_on(self):  # type: ignore[override]
        """Return whether this light is on or off."""
        if "LIGHT_LEVEL" in self.extra_state_attributes:
            return self.extra_state_attributes["LIGHT_LEVEL"] > 0
        if "Brightness Percent" in self.extra_state_attributes:
            return self.extra_state_attributes["Brightness Percent"] > 0
        if "LIGHT_STATE" in self.extra_state_attributes:
            return self.extra_state_attributes["LIGHT_STATE"] > 0
        if "CURRENT_POWER" in self.extra_state_attributes:
            return self.extra_state_attributes["CURRENT_POWER"] > 0
        # Return false if no match found
        return False
    
    @property
    def brightness(self):  # type: ignore[override]
        """Return the brightness of this light between 0..255."""
        if "LIGHT_LEVEL" in self.extra_state_attributes:
            return value_to_brightness(
                CONTROL4_BRIGHTNESS_SCALE, self.extra_state_attributes["LIGHT_LEVEL"]
            )
        if "Brightness Percent" in self.extra_state_attributes:
            return value_to_brightness(
                CONTROL4_BRIGHTNESS_SCALE,
                self.extra_state_attributes["Brightness Percent"],
            )
            
    @property
    def color_temp_kelvin(self) -> int | None:
        attrs = self.extra_state_attributes
        mode = attrs.get("light_color_current_color_mode")
        cct = attrs.get("light_color_current_color_correlated_temperature")

        if mode is not None and int(mode) == CONTROL4_COLOR_MODE_CCT and cct is not None:  # type: ignore[arg-type]
            ct = int(cct)
            return ct
        return None

    @property
    def min_color_temp_kelvin(self) -> int | None:  # type: ignore[override]
        if self._ct_min is not None:
            return int(self._ct_min)
        return self._attr_min_color_temp_kelvin

    @property
    def max_color_temp_kelvin(self) -> int | None:  # type: ignore[override]
        if self._ct_max is not None:
            return int(self._ct_max)
        return self._attr_max_color_temp_kelvin

    @property
    def effect(self) -> str | None:  # type: ignore[override]
        return self._current_effect

    @property
    def effect_list(self) -> list[str] | None:  # type: ignore[override]
        return sorted(self._effects_by_name) or None

    @property
    def supported_features(self) -> LightEntityFeature:  # type: ignore[override]
        features = LightEntityFeature(0)
        if self._is_dimmer or self._supports_color or self._supports_ct:
            features |= LightEntityFeature.TRANSITION
        if self._effects_by_name:
            features |= LightEntityFeature.EFFECT
        return features

    @property
    def _is_dimmer(self):
        return bool("LIGHT_LEVEL" in self.extra_state_attributes) or bool(
            "Brightness Percent" in self.extra_state_attributes
        )

    @property
    def color_mode(self) -> ColorMode | None:  # type: ignore[override]
        attrs = self.extra_state_attributes
        mode = attrs.get("light_color_current_color_mode")
        try:
            mode_i = int(mode)  # type: ignore[arg-type]
            if mode_i == CONTROL4_COLOR_MODE_CCT:
                return ColorMode.COLOR_TEMP
            if mode_i == CONTROL4_COLOR_MODE_XY:
                return ColorMode.XY
        except (ValueError, TypeError):
            pass
        if self._attr_color_mode in (self._attr_supported_color_modes or set()):
            return self._attr_color_mode
        return ColorMode.UNKNOWN
            
    @property
    def xy_color(self) -> tuple[float, float] | None:  # type: ignore[override]
        attrs = self.extra_state_attributes
        x = attrs.get("light_color_current_x")
        y = attrs.get("light_color_current_y")
        if x is not None and y is not None:
            return (float(x), float(y))
        return None


    # -----------------------
    # Commands
    # -----------------------

    def _to_rate_ms(self, transition: float | int | None) -> int | None:
        if transition is None:
            return None
        try:
            rate = int(float(transition) * 1000)
        except Exception:  # noqa: BLE001
            return None
        if self._rate_min is not None:
            rate = max(rate, int(self._rate_min))
        if self._rate_max is not None:
            rate = min(rate, int(self._rate_max))
        return max(0, rate)

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the entity on (brightness / color / CCT / effect)."""
        c4_light = self.create_api_object()

        # Transition -> ms (rate)
        transition_length = self._to_rate_ms(kwargs.get(ATTR_TRANSITION))

        # ----- Effect (preset) -----
        effect = kwargs.get(ATTR_EFFECT)
        if effect and effect in self._effects_by_name:
            preset = self._effects_by_name[effect]

            ct = preset.get("color_correlated_temperature")
            if isinstance(ct, (int, float)) and ct > 0 and self._supports_ct:
                ct_i = int(ct)
                if self._ct_min:
                    ct_i = max(ct_i, int(self._ct_min))
                if self._ct_max:
                    ct_i = min(ct_i, int(self._ct_max))
                await c4_light.set_color_temperature(ct_i, rate=transition_length)
                self._attr_color_mode = ColorMode.COLOR_TEMP
            else:
                x = preset.get("color_x")
                y = preset.get("color_y")
                if (
                    self._supports_color
                    and isinstance(x, (int, float))
                    and isinstance(y, (int, float))
                ):
                    await c4_light.set_color_xy(float(x), float(y), rate=transition_length)
                    self._attr_color_mode = ColorMode.XY
            self._current_effect = effect
            self.async_write_ha_state()
            return

        # ----- XY Color -----
        if ATTR_XY_COLOR in kwargs and self._supports_color:
            x, y = kwargs[ATTR_XY_COLOR]
            await c4_light.set_color_xy(float(x), float(y), rate=transition_length)
            self._current_effect = None
            self._attr_color_mode = ColorMode.XY
            self.async_write_ha_state()
            return

        # ----- Color Temperature (Kelvin) -----
        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._supports_ct:
            ct = int(kwargs[ATTR_COLOR_TEMP_KELVIN])
            if self._ct_min is not None:
                ct = max(ct, int(self._ct_min))
            if self._ct_max is not None:
                ct = min(ct, int(self._ct_max))
            await c4_light.set_color_temperature(ct, rate=transition_length)
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._current_effect = None
            self.async_write_ha_state()
            return
        
        # ----- 4) Brightness / On -----
        if self._is_dimmer:
            if ATTR_BRIGHTNESS in kwargs:
                brightness = round(
                    brightness_to_value(CONTROL4_BRIGHTNESS_SCALE, kwargs[ATTR_BRIGHTNESS])
                )
            else:
                # if no brightness provided but we need to "turn on"
                brightness = 100
            await c4_light.ramp_to_level(brightness, transition_length or 0)
        else:
            # If not dimmer but color/CCT supported, a color command may suffice
            # Otherwise we force ON
            if not (ATTR_XY_COLOR in kwargs or ATTR_COLOR_TEMP_KELVIN in kwargs or effect):
                await c4_light.set_level(100)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        c4_light = self.create_api_object()
        transition_length = self._to_rate_ms(kwargs.get(ATTR_TRANSITION))
        if self._is_dimmer:
            await c4_light.ramp_to_level(0, transition_length or 0)
        else:
            await c4_light.set_level(0)
