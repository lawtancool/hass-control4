"""Platform for Control4 Lua-based sensors (e.g., dynalite_trigger)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Control4Entity
from .const import CONF_DIRECTOR_ALL_ITEMS, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

LUA_CONTROL = "lua_gen"
PROXY_DYNALITE_TRIGGER = "dynalite_trigger"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 Lua-based sensors from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    all_items: list[dict[str, Any]] = entry_data[CONF_DIRECTOR_ALL_ITEMS]

    # Identify Lua-driven "trigger" devices (common pattern: dynalite_trigger via lua_gen)
    lua_trigger_items: list[dict[str, Any]] = [
        item
        for item in all_items
        if item.get("type") == CONTROL4_ENTITY_TYPE
        and item.get("id")
        and (
            item.get("control") == LUA_CONTROL
            or item.get("protocolControl") == LUA_CONTROL
            or item.get("proxy") == PROXY_DYNALITE_TRIGGER
        )
    ]

    # Build quick lookup by id for parent data
    items_by_id = {item.get("id"): item for item in all_items if "id" in item}

    entities: list[Control4LuaSensor] = []

    for item in lua_trigger_items:
        try:
            item_name = str(item["name"])
            item_id = item["id"]
            item_area = item.get("roomName")
            item_parent_id = item.get("parentId")

            parent = items_by_id.get(item_parent_id)
            item_manufacturer = parent.get("manufacturer") if parent else None
            item_device_name = parent.get("name") if parent else None
            item_model = parent.get("model") if parent else None
        except KeyError:
            _LOGGER.exception(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue

        attributes = await director_get_entry_variables(hass, entry, item_id)

        entities.append(
            Control4LuaSensor(
                entry_data=entry_data,
                entry=entry,
                name=item_name,
                idx=item_id,
                device_name=item_device_name,
                device_manufacturer=item_manufacturer,
                device_model=item_model,
                device_id=item_parent_id,
                device_area=item_area,
                device_attributes=attributes,
                proxy=item.get("proxy"),
            )
        )

    if entities:
        async_add_entities(entities, True)
    else:
        _LOGGER.debug("No Lua-based sensors found")


class Control4LuaSensor(Control4Entity, SensorEntity):
    """Control4 Lua trigger sensor.

    Exposes the last received preset/event id as the sensor value, when available.
    All received fields are stored in extra_state_attributes for transparency.
    """

    _attr_native_value: int | str | None = None

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
        proxy: str | None,
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
        self._proxy = proxy or ""
        self._attr_available = True
        # Attempt to initialize native value from known fields if present
        self._derive_native_value_from_attributes()

    def _derive_native_value_from_attributes(self) -> None:
        """Derive native value from existing attributes."""
        # Heuristics: prefer explicit numeric fields that look like event/preset ids
        for key in ("preset", "event", "event_id", "preset_id", "Preset", "Event"):
            if key in self._extra_state_attributes:
                try:
                    self._attr_native_value = int(self._extra_state_attributes[key])
                except (ValueError, TypeError):
                    self._attr_native_value = self._extra_state_attributes[key]
                return
        self._attr_native_value = None

    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update."""
        if message is False:
            self._attr_available = False
        elif message.get("evtName") == "OnDataToUI":
            self._attr_available = True
            data = message.get("data", {})

            # Common pattern: devicecommand payloads for Lua drivers
            if "devicecommand" in data:
                payload = data["devicecommand"]
                # Some drivers nest under 'params'
                params = payload.get("params", payload) if isinstance(payload, dict) else {}
                if isinstance(params, dict):
                    # Merge into attributes
                    await self._data_to_extra_state_attributes(params)
                    # Try to detect/derive a native value
                    self._derive_native_value_from_attributes()
            else:
                # Fallback: record any other key/values
                await self._data_to_extra_state_attributes(data)
                self._derive_native_value_from_attributes()

        self.async_write_ha_state()

    @property
    def native_value(self) -> int | str | None:
        return self._attr_native_value

    @property
    def extra_state_attributes(self) -> dict:
        attrs = super().extra_state_attributes
        attrs["proxy_type"] = self._proxy
        return attrs

