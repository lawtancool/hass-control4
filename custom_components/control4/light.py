"""Platform for Control4 Lights."""
from __future__ import annotations
from typing import Any

import json
import logging

from pyControl4.light import C4Light

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_TRANSITION,
    ATTR_HS_COLOR,
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
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "lights"
CONTROL4_BRIGHTNESS_SCALE = (1, 100)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 lights from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]

    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)

    entity_list = []

    for item in items_of_category:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["id"]:
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
            Control4Light(
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


class Control4Light(Control4Entity, LightEntity):
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
        self._cached_hs: tuple[float, float] | None = None
        self._cached_ct: int | None = None
        self._last_color_mode: ColorMode | None = None
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
            resp = await director.getItemSetup(self._idx)
            if isinstance(resp, str):
                resp = json.loads(resp)

            setup = resp.get("setup", resp) if isinstance(resp, dict) else {}

            if isinstance(setup, str):
                setup = json.loads(setup)

            self._supports_color = bool(setup.get("supports_color"))
            #self._supports_ct = bool(setup.get("supports_color_correlated_temperature"))
            self._supports_ct = False

            colors = setup.get("colors") or {}
            if self._supports_ct:
                self._ct_min = (colors.get("color_correlated_temperature_min") or 2000)
                self._ct_max = (colors.get("color_correlated_temperature_max") or 6500)
                
                self._attr_min_color_temp_kelvin = int(self._ct_min)
                self._attr_max_color_temp_kelvin = int(self._ct_max)

            self._rate_min = colors.get("color_rate_min")
            self._rate_max = colors.get("color_rate_max")

            # presets
            for pr in colors.get("color") or []:
                name = pr.get("name")
                if name:
                    self._effects_by_name[name] = pr

            # calculate supported_color_modes now that setup is parsed
            modes = set()
            if self._is_dimmer:
                modes.add(ColorMode.BRIGHTNESS)
            if self._supports_color:
                modes.add(ColorMode.HS)
            if self._supports_ct:
                modes.add(ColorMode.COLOR_TEMP)
            if not modes:
                modes = {ColorMode.ONOFF}
            self._attr_supported_color_modes = modes

            # choose initial color_mode
            if ColorMode.HS in modes and not self._is_dimmer:
                self._attr_color_mode = ColorMode.HS
            elif ColorMode.COLOR_TEMP in modes and not self._is_dimmer:
                self._attr_color_mode = ColorMode.COLOR_TEMP
            else:
                self._attr_color_mode = ColorMode.BRIGHTNESS if self._is_dimmer else ColorMode.ONOFF

            _LOGGER.debug("Parsed setup for %s: supports_color=%s supports_ct=%s modes=%s",
                        self._idx, self._supports_color, self._supports_ct, self._attr_supported_color_modes)

        except Exception as exc:
            _LOGGER.debug("getItemSetup failed for %s: %s", self._idx, exc)

        self.async_write_ha_state()


    @property
    def is_on(self):
        """Return whether this light is on or off."""
        if "LIGHT_LEVEL" in self.extra_state_attributes:
            return self.extra_state_attributes["LIGHT_LEVEL"] > 0
        if "Brightness Percent" in self.extra_state_attributes:
            return self.extra_state_attributes["Brightness Percent"] > 0
        if "LIGHT_STATE" in self.extra_state_attributes:
            return self.extra_state_attributes["LIGHT_STATE"] > 0
        if "CURRENT_POWER" in self.extra_state_attributes:
            return self.extra_state_attributes["CURRENT_POWER"] > 0

    @property
    def brightness(self):
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
    def hs_color(self) -> tuple[float, float] | None:
        return self._cached_hs

    @property
    def color_temp_kelvin(self) -> int | None:
        return self._cached_ct

    @property
    def min_color_temp_kelvin(self) -> int | None:
        return self._ct_min

    @property
    def max_color_temp_kelvin(self) -> int | None:
        return self._ct_max

    @property
    def effect(self) -> str | None:
        return self._current_effect

    @property
    def effect_list(self) -> list[str] | None:
        return sorted(self._effects_by_name) or None

    # -----------------------
    # Properties
    # -----------------------

    @property
    def supported_features(self) -> int:
        features = 0
        if self._is_dimmer or self._supports_color or self._supports_ct:
            features |= LightEntityFeature.TRANSITION
        if self._effects_by_name:
            features |= LightEntityFeature.EFFECT
        return features

    @property
    def color_mode(self) -> ColorMode:
        if getattr(self, "_last_color_mode", None):
            return self._last_color_mode
        return ColorMode.BRIGHTNESS if self._is_dimmer else ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        modes: set[ColorMode] = set()
        if self._is_dimmer:
            modes.add(ColorMode.BRIGHTNESS)
        if getattr(self, "_supports_color", False):
            modes.add(ColorMode.HS)
        if getattr(self, "_supports_ct", False):
            modes.add(ColorMode.COLOR_TEMP)
        return modes or {ColorMode.ONOFF}

    @property
    def _is_dimmer(self):
        return bool("LIGHT_LEVEL" in self.extra_state_attributes) or bool(
            "Brightness Percent" in self.extra_state_attributes
        )

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
                await c4_light.setColorTemperature(ct_i, rate=transition_length)
                self._cached_ct = ct_i
                self._cached_hs = None
                self._last_color_mode = ColorMode.COLOR_TEMP
            else:
                x = preset.get("color_x")
                y = preset.get("color_y")
                if (
                    self._supports_color
                    and isinstance(x, (int, float))
                    and isinstance(y, (int, float))
                ):
                    await c4_light.setColorXY(float(x), float(y), rate=transition_length, mode=0)
                    self._cached_hs = None 
                    self._cached_ct = None
                    self._last_color_mode = ColorMode.HS
            self._current_effect = effect

        # ----- Color HS -----
        if ATTR_HS_COLOR in kwargs and self._supports_color:
            h, s = kwargs[ATTR_HS_COLOR]
            r, g, b = self._hs_to_rgb(h, s)
            await c4_light.setColorRGB(r, g, b, rate=transition_length)
            self._cached_hs = (float(h), float(s))
            self._cached_ct = None
            self._last_color_mode = ColorMode.HS
            self._current_effect = None

        # ----- Color Temperature (Kelvin) -----
        if ATTR_COLOR_TEMP_KELVIN in kwargs and self._supports_ct:
            ct = int(kwargs[ATTR_COLOR_TEMP_KELVIN])
            if self._ct_min is not None:
                ct = max(ct, int(self._ct_min))
            if self._ct_max is not None:
                ct = min(ct, int(self._ct_max))
            await c4_light.setColorTemperature(ct, rate=transition_length)
            self._cached_ct = ct
            self._cached_hs = None
            self._last_color_mode = ColorMode.COLOR_TEMP
            self._current_effect = None

        # ----- 4) Brightness / On -----
        if self._is_dimmer:
            if ATTR_BRIGHTNESS in kwargs:
                brightness = round(
                    brightness_to_value(CONTROL4_BRIGHTNESS_SCALE, kwargs[ATTR_BRIGHTNESS])
                )
            else:
                # if no brightness provided but we need to "turn on"
                brightness = 100
            await c4_light.rampToLevel(brightness, transition_length or 0)
        else:
            # If not dimmer but color/CCT supported, a color command may suffice
            # Otherwise we force ON
            if not (ATTR_HS_COLOR in kwargs or ATTR_COLOR_TEMP_KELVIN in kwargs or effect):
                await c4_light.setLevel(100)

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the entity off."""
        c4_light = self.create_api_object()
        transition_length = self._to_rate_ms(kwargs.get(ATTR_TRANSITION))
        if self._is_dimmer:
            await c4_light.rampToLevel(0, transition_length or 0)
        else:
            await c4_light.setLevel(0)

    @staticmethod
    def _hs_to_rgb(h: float, s: float) -> tuple[int, int, int]:
        """HS(0..360, 0..100) -> RGB(0..255). V=1, brightness managed by ATTR_BRIGHTNESS."""
        h = float(h) % 360.0
        s = max(0.0, min(100.0, float(s))) / 100.0
        v = 1.0
        c = v * s
        x = c * (1 - abs((h / 60.0) % 2 - 1))
        m = v - c
        if 0 <= h < 60:
            rp, gp, bp = c, x, 0
        elif 60 <= h < 120:
            rp, gp, bp = x, c, 0
        elif 120 <= h < 180:
            rp, gp, bp = 0, c, x
        elif 180 <= h < 240:
            rp, gp, bp = 0, x, c
        elif 240 <= h < 300:
            rp, gp, bp = x, 0, c
        else:
            rp, gp, bp = c, 0, x
        r = int(round((rp + m) * 255))
        g = int(round((gp + m) * 255))
        b = int(round((bp + m) * 255))
        return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))