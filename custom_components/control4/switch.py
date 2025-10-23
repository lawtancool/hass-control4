"""Platform for Control4 Switches."""
from __future__ import annotations

import asyncio
import logging

from pyControl4.relay import C4Relay

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import Control4Entity
from .const import CONF_DIRECTOR, CONF_DIRECTOR_ALL_ITEMS, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

# Control4 proxy types for different relay devices, excluding locks
CONTROL4_RELAY_PROXY_TYPES = {
    "relaysingle_relay_c4": "Basic Relay",  # Generic relay that can be used for various purposes
    "cardaccess_wirelessrelay": "Wireless Relay",
    "relaysingle_electronicgate_c4": "Electronic Gate Relay",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up Control4 switches from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    director_all_items = entry_data[CONF_DIRECTOR_ALL_ITEMS]

    # Filter for relay devices, excluding lock relays which are handled by the lock platform
    relay_devices = [
        item for item in director_all_items
        if item.get("proxy") in CONTROL4_RELAY_PROXY_TYPES
    ]

    entity_list = []

    for item in relay_devices:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["id"]:
                item_name = str(item["name"])
                item_id = item["id"]
                item_area = item["roomName"]
                item_parent_id = item["parentId"]
                item_proxy = item.get("proxy", "")
                item_manufacturer = item.get("manufacturer")
                item_device_name = item.get("name")
                item_model = item.get("model")
            else:
                continue
        except KeyError:
            _LOGGER.exception(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue

        item_attributes = await director_get_entry_variables(hass, entry, item_id)

        # Only add if it has RelayState attribute
        if "RelayState" in item_attributes:
            entity_list.append(
                Control4Switch(
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
                    item_proxy,
                )
            )

    async_add_entities(entity_list, True)


class Control4Switch(Control4Entity, SwitchEntity):
    """Control4 switch entity."""

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
        proxy_type: str,
    ) -> None:
        """Initialize Control4 switch entity."""
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
        self._proxy_type = proxy_type
        self._attr_available = True
        # Initialize state from attributes
        if "RelayState" in self._extra_state_attributes:
            self._attr_is_on = self._extra_state_attributes["RelayState"] == 1

    def create_api_object(self):
        """Create a pyControl4 device object.

        This exists so the director token used is always the latest one, without needing to re-init the entire entity.
        """
        return C4Relay(self.entry_data[CONF_DIRECTOR], self._idx)

    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update for our item id/parent device id."""
        # Message will be False when a Websocket disconnect is detected
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]
            if "relay_state" in data:
                current_state = data["relay_state"].pop("current_state")
                if current_state == "CLOSED":
                    self._extra_state_attributes["RelayState"] = 1
                    self._attr_is_on = True
                elif current_state == "OPENED":
                    self._extra_state_attributes["RelayState"] = 0
                    self._attr_is_on = False
                else:
                    _LOGGER.error("Unknown relay state %s", current_state)
                await self._data_to_extra_state_attributes(data["relay_state"])

        _LOGGER.debug("Message for device %s", device)
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Return whether the switch is on."""
        return self._attr_is_on

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        c4_relay = self.create_api_object()
        try:
            await c4_relay.close()
        except Exception as err:
            _LOGGER.error("Error controlling relay: %s", err)
            # Make sure the relay is opened if there's an error
            try:
                await c4_relay.open()
            except Exception:
                pass

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        c4_relay = self.create_api_object()
        try:
            await c4_relay.open()
        except Exception as err:
            _LOGGER.error("Error controlling relay: %s", err)
    
    async def async_toggle(self, **kwargs):
        """Toggle relay."""
        c4_relay = self.create_api_object()
        try:
            await c4_relay.toggle()
        except Exception as err:
            _LOGGER.error("Error controlling relay: %s", err)


    @property
    def extra_state_attributes(self):
        """Return entity specific state attributes."""
        attrs = super().extra_state_attributes
        attrs["proxy_type"] = self._proxy_type
        attrs["proxy_type_name"] = CONTROL4_RELAY_PROXY_TYPES.get(self._proxy_type, "Unknown")
        return attrs 
