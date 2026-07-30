"""Control4 pool/spa (Pentair IntelliCenter) entities."""
from __future__ import annotations

import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
    FAN_OFF,
    FAN_ON,
)
from homeassistant.components.number import NumberEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Control4Entity
from .const import (
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_POOL_DEVICES,
    CONF_POOL_LIGHT_AUX_ID,
    CONF_SPA_BLOWER_AUX_ID,
    CONF_SPA_LIGHT_AUX_ID,
    CONTROL4_ENTITY_TYPE,
    DOMAIN,
    POOL_AUX_SLOT_COUNT,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_POOL_PROXY = "pool"


def configured_aux_circuits(entry: ConfigEntry) -> list[PoolAuxButton]:
    """Return aux circuits the user named in Options (slots 1–5).

    Falls back to legacy role-based option keys so existing installs keep working
    until the user re-saves Configure.
    """
    options = entry.options
    circuits: list[PoolAuxButton] = []
    for aux_id in range(1, POOL_AUX_SLOT_COUNT + 1):
        name = options.get(f"pool_aux_{aux_id}_name")
        if isinstance(name, str) and name.strip():
            circuits.append(
                PoolAuxButton(
                    aux_id=aux_id, name=name.strip(), aux_type="TOGGLE"
                )
            )
    if circuits:
        return circuits

    # Legacy: pool_light_aux_id / spa_light_aux_id / spa_blower_aux_id
    legacy = (
        (CONF_POOL_LIGHT_AUX_ID, "Pool Light"),
        (CONF_SPA_LIGHT_AUX_ID, "Spa Light"),
        (CONF_SPA_BLOWER_AUX_ID, "Air Blower"),
    )
    for key, label in legacy:
        raw = options.get(key)
        if raw in (None, ""):
            continue
        try:
            aux_id = int(raw)
        except (TypeError, ValueError):
            continue
        if aux_id < 1:
            continue
        circuits.append(PoolAuxButton(aux_id=aux_id, name=label, aux_type="TOGGLE"))
    return circuits


@dataclass
class PoolHeatMode:
    """A single pool or spa heat mode from pool_setup."""

    mode_id: int
    text: str
    command: str


@dataclass
class PoolAuxButton:
    """An auxiliary control button from BUTTON_NAMES."""

    aux_id: int
    name: str
    aux_type: str


@dataclass
class PoolDeviceInfo:
    """Discovered Control4 pool controller item."""

    item_id: int
    item_name: str
    item_area: str | None
    parent_id: int
    parent_name: str | None
    parent_manufacturer: str | None
    parent_model: str | None
    attributes: dict[str, Any]
    setup: dict[str, Any] = field(default_factory=dict)
    heat_modes: dict[str, list[PoolHeatMode]] = field(default_factory=dict)
    pump_modes: dict[str, list[str]] = field(default_factory=dict)
    temp_min: float = 40
    temp_max: float = 104
    scale: str = "F"
    aux_buttons: list[PoolAuxButton] = field(default_factory=list)
    aux_states: dict[int, bool] = field(default_factory=dict)


def parse_pool_xml_list(xml_text: str) -> list[dict[str, str]]:
    """Parse Control4 pool proxy XML list payloads."""
    if not xml_text or not str(xml_text).strip():
        return []
    text = str(xml_text).strip()
    if not text.startswith("<"):
        return []
    try:
        root = ET.fromstring(text if text.startswith("<items") else f"<items>{text}</items>")
    except ET.ParseError:
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return []
    items: list[dict[str, str]] = []
    for item in root.iter("item"):
        entry = {
            child.tag: (child.text or "").strip()
            for child in item
            if child.tag
        }
        if entry:
            items.append(entry)
    return items


def parse_aux_buttons(attributes: dict[str, Any]) -> list[PoolAuxButton]:
    """Parse BUTTON_NAMES variable into aux button metadata."""
    buttons: list[PoolAuxButton] = []
    for entry in parse_pool_xml_list(str(attributes.get("BUTTON_NAMES", ""))):
        try:
            aux_id = int(entry.get("id", ""))
        except (TypeError, ValueError):
            continue
        name = entry.get("item_text") or entry.get("name") or f"Aux {aux_id}"
        aux_type = entry.get("type") or "TOGGLE"
        buttons.append(PoolAuxButton(aux_id=aux_id, name=name, aux_type=aux_type))
    return buttons


def parse_aux_states(attributes: dict[str, Any]) -> dict[int, bool]:
    """Parse AUXMODES variable into on/off state by aux id."""
    states: dict[int, bool] = {}
    for entry in parse_pool_xml_list(str(attributes.get("AUXMODES", ""))):
        try:
            aux_id = int(entry.get("id", ""))
        except (TypeError, ValueError):
            continue
        mode = (entry.get("mode") or "").upper()
        states[aux_id] = mode in {"ON", "Y", "TRUE", "1"}
    return states


def _parse_heat_modes(setup: dict[str, Any], key: str) -> list[PoolHeatMode]:
    modes: list[PoolHeatMode] = []
    raw = setup.get(key)
    if not isinstance(raw, dict):
        return modes
    entries = raw.get("mode")
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        return modes
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        try:
            mode_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        modes.append(
            PoolHeatMode(
                mode_id=mode_id,
                text=str(entry.get("text") or ""),
                command=str(entry.get("command") or ""),
            )
        )
    return modes


def _parse_pump_modes(setup: dict[str, Any], key: str) -> list[str]:
    raw = setup.get(key)
    if not isinstance(raw, str) or not raw.strip():
        return ["Off", "On"]
    return [part.strip() for part in raw.split(",") if part.strip()]


async def load_pool_setup(hass: HomeAssistant, entry: ConfigEntry, item_id: int) -> dict[str, Any]:
    """Fetch pool_setup via GET_SETUP."""
    director = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR]
    raw = await director.get_item_setup(item_id)
    if isinstance(raw, str):
        data = json.loads(raw)
    elif isinstance(raw, dict):
        data = raw
    else:
        return {}
    return data.get("pool_setup") or {}


async def discover_pool_devices(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[PoolDeviceInfo]:
    """Discover pool proxy devices and load setup/variables."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    if CONF_POOL_DEVICES in entry_data:
        return entry_data[CONF_POOL_DEVICES]

    all_items: list[dict[str, Any]] = entry_data[CONF_DIRECTOR_ALL_ITEMS]
    items_by_id = {item.get("id"): item for item in all_items if item.get("id")}

    devices: list[PoolDeviceInfo] = []
    for item in all_items:
        if item.get("type") != CONTROL4_ENTITY_TYPE:
            continue
        if item.get("proxy") != CONTROL4_POOL_PROXY:
            continue
        item_id = item.get("id")
        if not item_id:
            continue

        parent = items_by_id.get(item.get("parentId")) or {}
        attributes = await director_get_entry_variables(hass, entry, item_id)
        setup = await load_pool_setup(hass, entry, item_id)

        devices.append(
            PoolDeviceInfo(
                item_id=item_id,
                item_name=str(item.get("name") or "Pool"),
                item_area=item.get("roomName"),
                parent_id=item.get("parentId"),
                parent_name=parent.get("name"),
                parent_manufacturer=parent.get("manufacturer"),
                parent_model=parent.get("model"),
                attributes=attributes,
                setup=setup,
                heat_modes={
                    "pool": _parse_heat_modes(setup, "pool_heat_modes"),
                    "spa": _parse_heat_modes(setup, "spa_heat_modes"),
                },
                pump_modes={
                    "pool": _parse_pump_modes(setup, "pool_pumpmodes"),
                    "spa": _parse_pump_modes(setup, "spa_pumpmodes"),
                },
                temp_min=float(setup.get("temp_min", 40)),
                temp_max=float(setup.get("temp_max", 104)),
                scale=str(attributes.get("SCALE") or "F"),
                aux_buttons=parse_aux_buttons(attributes),
                aux_states=parse_aux_states(attributes),
            )
        )
    entry_data[CONF_POOL_DEVICES] = devices
    return devices


async def send_pool_command(
    entry_data: dict, item_id: int, command: str, params: dict[str, Any]
) -> None:
    """Send a pool proxy command to the Control4 director."""
    director = entry_data[CONF_DIRECTOR]
    await director.send_post_request(
        f"/api/v1/items/{item_id}/commands",
        command,
        params,
    )


class Control4PoolEntity(Control4Entity):
    """Shared base for pool controller child entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        pool: PoolDeviceInfo,
        entity_suffix: str,
        name: str,
    ) -> None:
        super().__init__(
            entry_data,
            entry,
            name,
            pool.item_id,
            pool.parent_name,
            pool.parent_manufacturer,
            pool.parent_model,
            pool.parent_id,
            pool.item_area,
            dict(pool.attributes),
        )
        self.pool = pool
        self._attr_unique_id = f"{pool.item_id}_{entity_suffix}"


class Control4PoolSetpointNumber(Control4PoolEntity, NumberEntity):
    """Pool or spa water temperature setpoint."""

    _attr_native_step = 1.0
    _attr_mode = "box"

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        pool: PoolDeviceInfo,
        *,
        zone: str,
        var_name: str,
        command: str,
        friendly_name: str,
    ) -> None:
        super().__init__(entry_data, entry, pool, f"{zone}_setpoint", friendly_name)
        self._var_name = var_name
        self._command = command
        self._attr_native_min_value = pool.temp_min
        self._attr_native_max_value = pool.temp_max
        self._attr_native_unit_of_measurement = (
            UnitOfTemperature.FAHRENHEIT
            if pool.scale.upper().startswith("F")
            else UnitOfTemperature.CELSIUS
        )

    def _read_setpoint(self) -> float | None:
        raw = self._extra_state_attributes.get(self._var_name)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def native_value(self) -> float | None:  # type: ignore[override]
        return self._read_setpoint()

    async def async_set_native_value(self, value: float) -> None:
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._command,
            {"SETPOINT": int(round(value))},
        )

    async def _update_callback(self, device, message):
        if message is False:
            self._attr_available = False
        elif message.get("evtName") == "OnDataToUI":
            self._attr_available = True
            data = message.get("data") or {}
            await self._data_to_extra_state_attributes(data)
            for key in (self._var_name, self._var_name.lower(), "setpoint"):
                if key in data:
                    try:
                        self._attr_native_value = float(data[key])
                    except (TypeError, ValueError):
                        pass
        self.async_write_ha_state()


class Control4PoolPumpSwitch(Control4PoolEntity, SwitchEntity):
    """Pool or spa pump on/off."""

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        pool: PoolDeviceInfo,
        *,
        zone: str,
        var_name: str,
        command: str,
        friendly_name: str,
    ) -> None:
        super().__init__(entry_data, entry, pool, f"{zone}_pump", friendly_name)
        self._zone = zone
        self._var_name = var_name
        self._command = command
        modes = pool.pump_modes.get(zone) or ["Off", "On"]
        self._off_mode = modes[0]
        self._on_mode = modes[-1] if len(modes) > 1 else "On"
        self._attr_is_on = self._read_is_on()

    def _read_is_on(self) -> bool:
        value = str(self._extra_state_attributes.get(self._var_name, "")).strip()
        return value.lower() not in {"", "off", "0", "false"}

    @property
    def is_on(self) -> bool:  # type: ignore[override]
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._command,
            {"PUMPMODE": self._on_mode},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._command,
            {"PUMPMODE": self._off_mode},
        )

    async def _update_callback(self, device, message):
        if message is False:
            self._attr_available = False
        elif message.get("evtName") == "OnDataToUI":
            self._attr_available = True
            data = message.get("data") or {}
            await self._data_to_extra_state_attributes(data)
            if self._var_name in data:
                self._attr_is_on = str(data[self._var_name]).strip().lower() not in {
                    "",
                    "off",
                    "0",
                    "false",
                }
        self.async_write_ha_state()


class Control4PoolHeatSwitch(Control4PoolEntity, SwitchEntity):
    """Pool or spa heater on/off."""

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        pool: PoolDeviceInfo,
        *,
        zone: str,
        var_name: str,
        command: str,
        friendly_name: str,
    ) -> None:
        super().__init__(entry_data, entry, pool, f"{zone}_heater", friendly_name)
        self._zone = zone
        self._var_name = var_name
        self._command = command
        self._heat_modes = pool.heat_modes.get(zone) or []
        self._primary_mode = self._heat_modes[0] if self._heat_modes else None
        self._attr_is_on = self._read_is_on()

    def _read_is_on(self) -> bool:
        value = str(self._extra_state_attributes.get(self._var_name, "")).strip()
        if not value:
            return False
        return value.lower() not in {"off", "0", "false"}

    @property
    def is_on(self) -> bool:  # type: ignore[override]
        return self._attr_is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._primary_mode:
            return
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._command,
            {"MODE": "ON", "ID": self._primary_mode.mode_id},
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not self._primary_mode:
            return
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._command,
            {"MODE": "OFF", "ID": self._primary_mode.mode_id},
        )

    async def _update_callback(self, device, message):
        if message is False:
            self._attr_available = False
        elif message.get("evtName") == "OnDataToUI":
            self._attr_available = True
            data = message.get("data") or {}
            await self._data_to_extra_state_attributes(data)
            if self._var_name in data:
                value = str(data[self._var_name]).strip()
                self._attr_is_on = value.lower() not in {"", "off", "0", "false"}
            for xml_key in ("pool_heatstate", "spa_heatstate"):
                if xml_key in data:
                    self._attr_is_on = self._parse_heat_xml(data[xml_key])
        self.async_write_ha_state()

    def _parse_heat_xml(self, xml_text: Any) -> bool:
        if not xml_text:
            return False
        for entry in parse_pool_xml_list(str(xml_text)):
            if (entry.get("mode") or "").upper() == "ON":
                return True
        return False


class Control4PoolAuxSwitch(Control4PoolEntity, SwitchEntity):
    """Pool/spa auxiliary toggle (lights, blower, etc.)."""

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        pool: PoolDeviceInfo,
        *,
        aux_button: PoolAuxButton,
    ) -> None:
        super().__init__(
            entry_data,
            entry,
            pool,
            f"aux_{aux_button.aux_id}",
            aux_button.name,
        )
        self._aux_button = aux_button
        self._attr_is_on = self._read_is_on()

    @property
    def available(self) -> bool:  # type: ignore[override]
        return super().available and self._aux_button is not None

    def _read_is_on(self) -> bool:
        if not self._aux_button:
            return False
        return self.pool.aux_states.get(self._aux_button.aux_id, False)

    @property
    def is_on(self) -> bool:  # type: ignore[override]
        return self._attr_is_on

    def _sync_name_from_options(self) -> None:
        """Keep entity name aligned with Configure labels."""
        if not self._aux_button:
            return
        name = self.entry.options.get(f"pool_aux_{self._aux_button.aux_id}_name")
        if isinstance(name, str) and name.strip():
            self._aux_button = PoolAuxButton(
                aux_id=self._aux_button.aux_id,
                name=name.strip(),
                aux_type=self._aux_button.aux_type,
            )
            self._attr_name = name.strip()

    async def async_turn_on(self, **kwargs: Any) -> None:
        if not self._aux_button:
            return
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            "SET_AUX_MODE",
            {"ID": self._aux_button.aux_id, "MODE": "ON"},
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        if not self._aux_button:
            return
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            "SET_AUX_MODE",
            {"ID": self._aux_button.aux_id, "MODE": "OFF"},
        )
        self._attr_is_on = False
        self.async_write_ha_state()

    def _apply_aux_mode(self, aux_id: Any, mode: Any) -> bool:
        """Update on/off from a Control4 aux id/mode pair. Returns True if applied."""
        if not self._aux_button:
            return False
        try:
            if int(aux_id) != self._aux_button.aux_id:
                return False
        except (TypeError, ValueError):
            return False
        self._attr_is_on = str(mode or "").upper() in {"ON", "Y"}
        return True

    def _refresh_aux_state(self, attributes: dict[str, Any]) -> None:
        self._sync_name_from_options()
        states = parse_aux_states(attributes)
        # Empty AUXMODES must not clobber optimistic / item-based on/off
        if states:
            self.pool.aux_states = states
            self._attr_is_on = self._read_is_on()

    async def _update_callback(self, device, message):
        if message is False:
            self._attr_available = False
        elif message.get("evtName") == "OnDataToUI":
            self._attr_available = True
            data = message.get("data") or {}
            await self._data_to_extra_state_attributes(data)
            if data.get("AUXMODES"):
                self._refresh_aux_state(self._extra_state_attributes)
            for entry in parse_pool_xml_list(str(data.get("aux_state", ""))):
                self._apply_aux_mode(entry.get("id"), entry.get("mode"))
            # SET_AUX_MODE responses often include a single item dict, not aux_state XML
            item = data.get("item")
            if isinstance(item, dict):
                self._apply_aux_mode(item.get("id"), item.get("mode"))
        self.async_write_ha_state()


class Control4PoolClimate(Control4PoolEntity, ClimateEntity):
    """Pool or spa modeled as heat-only climate with pump as fan."""

    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1.0
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_fan_modes = [FAN_OFF, FAN_ON]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        entry_data: dict,
        entry: ConfigEntry,
        pool: PoolDeviceInfo,
        *,
        zone: str,
        friendly_name: str,
    ) -> None:
        super().__init__(entry_data, entry, pool, f"{zone}_climate", friendly_name)
        self._zone = zone
        if zone == "pool":
            self._temp_var = "POOL_TEMPERATURE"
            self._setpoint_var = "POOL_SETPOINT"
            self._setpoint_command = "SET_POOL_SETPOINT"
            self._pump_var = "PUMPMODE"
            self._pump_command = "SET_POOL_PUMPMODE"
            self._heat_var = "POOL_HEATMODE"
            self._heat_command = "SET_POOL_HEATMODE"
        else:
            self._temp_var = "SPA_TEMPERATURE"
            self._setpoint_var = "SPA_SETPOINT"
            self._setpoint_command = "SET_SPA_SETPOINT"
            self._pump_var = "SPAMODE"
            self._pump_command = "SET_SPA_PUMPMODE"
            self._heat_var = "SPA_HEATMODE"
            self._heat_command = "SET_SPA_HEATMODE"

        modes = pool.pump_modes.get(zone) or ["Off", "On"]
        self._pump_off = modes[0]
        self._pump_on = modes[-1] if len(modes) > 1 else "On"
        self._heat_modes = pool.heat_modes.get(zone) or []
        self._primary_heat = self._heat_modes[0] if self._heat_modes else None

        self._attr_min_temp = pool.temp_min
        self._attr_max_temp = pool.temp_max
        self._attr_temperature_unit = (
            UnitOfTemperature.FAHRENHEIT
            if pool.scale.upper().startswith("F")
            else UnitOfTemperature.CELSIUS
        )

    def _float_attr(self, key: str) -> float | None:
        raw = self._extra_state_attributes.get(key)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _is_heat_on(self) -> bool:
        value = str(self._extra_state_attributes.get(self._heat_var, "")).strip()
        if not value:
            return False
        return value.lower() not in {"off", "0", "false"}

    def _is_pump_on(self) -> bool:
        value = str(self._extra_state_attributes.get(self._pump_var, "")).strip()
        return value.lower() not in {"", "off", "0", "false"}

    @property
    def current_temperature(self) -> float | None:  # type: ignore[override]
        return self._float_attr(self._temp_var)

    @property
    def target_temperature(self) -> float | None:  # type: ignore[override]
        return self._float_attr(self._setpoint_var)

    @property
    def hvac_mode(self) -> HVACMode:  # type: ignore[override]
        return HVACMode.HEAT if self._is_heat_on() else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:  # type: ignore[override]
        if not self._is_heat_on():
            return HVACAction.OFF
        current = self.current_temperature
        target = self.target_temperature
        if current is not None and target is not None and current >= target:
            return HVACAction.IDLE
        return HVACAction.HEATING

    @property
    def fan_mode(self) -> str | None:  # type: ignore[override]
        return FAN_ON if self._is_pump_on() else FAN_OFF

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._setpoint_command,
            {"SETPOINT": int(round(float(temperature)))},
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if not self._primary_heat:
            _LOGGER.warning("No heat mode configured for %s", self.entity_id)
            return
        mode = "ON" if hvac_mode == HVACMode.HEAT else "OFF"
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._heat_command,
            {"MODE": mode, "ID": self._primary_heat.mode_id},
        )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        pump_mode = self._pump_on if fan_mode == FAN_ON else self._pump_off
        await send_pool_command(
            self.entry_data,
            self.pool.item_id,
            self._pump_command,
            {"PUMPMODE": pump_mode},
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def _update_callback(self, device, message):
        if message is False:
            self._attr_available = False
        elif message.get("evtName") == "OnDataToUI":
            self._attr_available = True
            data = message.get("data") or {}
            await self._data_to_extra_state_attributes(data)
            # Normalize common websocket key aliases into attributes
            aliases = {
                "temperature": self._temp_var,
                "setpoint": self._setpoint_var,
                "pumpmode": self._pump_var if self._zone == "pool" else None,
                "spamode": self._pump_var if self._zone == "spa" else None,
            }
            for src, dest in aliases.items():
                if dest and src in data:
                    self._extra_state_attributes[dest] = data[src]
            for xml_key in ("pool_heatstate", "spa_heatstate"):
                if xml_key not in data:
                    continue
                on = any(
                    (entry.get("mode") or "").upper() == "ON"
                    for entry in parse_pool_xml_list(str(data[xml_key]))
                )
                self._extra_state_attributes[self._heat_var] = "ON" if on else "Off"
        self.async_write_ha_state()


def build_pool_climate_entities(
    entry_data: dict, entry: ConfigEntry, pool: PoolDeviceInfo
) -> list[Control4PoolClimate]:
    """Build pool and spa climate entities."""
    return [
        Control4PoolClimate(
            entry_data,
            entry,
            pool,
            zone="pool",
            friendly_name="Pool",
        ),
        Control4PoolClimate(
            entry_data,
            entry,
            pool,
            zone="spa",
            friendly_name="Spa",
        ),
    ]


def build_pool_aux_switch_entities(
    entry_data: dict, entry: ConfigEntry, pool: PoolDeviceInfo
) -> list[Control4PoolAuxSwitch]:
    """Build aux switches for each named Configure slot (aux 1–5)."""
    return [
        Control4PoolAuxSwitch(entry_data, entry, pool, aux_button=aux)
        for aux in configured_aux_circuits(entry)
    ]


async def async_setup_pool_climates(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up pool/spa climate entities."""
    try:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        entities: list[ClimateEntity] = []
        for pool in await discover_pool_devices(hass, entry):
            entities.extend(build_pool_climate_entities(entry_data, entry, pool))
        if entities:
            async_add_entities(entities, True)
    except Exception:
        _LOGGER.exception("Error setting up Control4 pool/spa climate entities")


async def async_setup_pool_numbers(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Setpoints are exposed via climate entities; keep no standalone numbers."""
    return


async def async_setup_pool_switches(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up pool/spa aux switch entities (lights/blower)."""
    try:
        entry_data = hass.data[DOMAIN][entry.entry_id]
        entities: list[SwitchEntity] = []
        for pool in await discover_pool_devices(hass, entry):
            mapped = build_pool_aux_switch_entities(entry_data, entry, pool)
            if not mapped:
                _LOGGER.info(
                    "Pool item %s: no aux switches mapped. Set Pool light / Spa light / "
                    "Spa blower aux IDs under Control4 → Configure, or wait for "
                    "Director BUTTON_NAMES. See README “Pool / spa auxiliaries”.",
                    pool.item_id,
                )
            entities.extend(mapped)
        if entities:
            async_add_entities(entities, True)
    except Exception:
        _LOGGER.exception("Error setting up Control4 pool/spa switch entities")
