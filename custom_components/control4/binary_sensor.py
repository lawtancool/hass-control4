"""Platform for Control4 Binary Sensor."""
from __future__ import annotations

import json
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import Control4Entity, get_items_of_category
from .const import CONF_DIRECTOR, CONF_DIRECTOR_ALL_ITEMS, CONTROL4_ENTITY_TYPE, DOMAIN
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "sensors"
CONTROL4_CONTROL_TYPE = "control4_contactsingle"
CONTROL4_SENSOR_VAR = "ContactState"

CONTROL4_DOOR_PROXY = "contactsingle_doorcontactsensor_c4"
CONTROL4_WINDOW_PROXY = "contactsingle_windowcontactsensor_c4"
CONTROL4_MOTION_PROXY = "contactsingle_motionsensor_c4"
CONTROL4_GARAGE_DOOR_PROXY = "relaycontact_garagedoor_c4"

# List of proxy types that should be handled as switches instead of binary sensors
CONTROL4_RELAY_PROXY_TYPES = {
    "relaysingle_relay_c4",
    "relaysingle_doorlock_c4",
    "cardaccess_wirelessrelay",
}

CONTROL4_PROXY_MAPPING = {
    CONTROL4_DOOR_PROXY: BinarySensorDeviceClass.DOOR,
    CONTROL4_WINDOW_PROXY: BinarySensorDeviceClass.WINDOW,
    CONTROL4_MOTION_PROXY: BinarySensorDeviceClass.MOTION,
    CONTROL4_GARAGE_DOOR_PROXY: BinarySensorDeviceClass.GARAGE_DOOR,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up Control4 binary sensor from a config entry."""

    entry_data = hass.data[DOMAIN][entry.entry_id]
    director_all_items = entry_data[CONF_DIRECTOR_ALL_ITEMS]

    # Get items from sensors category
    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)
    _LOGGER.debug("Found %d items in sensors category", len(items_of_category))

    # Add garage door sensors from devices category, but only if they're not already in sensors
    existing_ids = {item["id"] for item in items_of_category}
    garage_door_sensors = [
        item for item in director_all_items
        if item.get("proxy") == CONTROL4_GARAGE_DOOR_PROXY and item["id"] not in existing_ids
    ]
    
    items_of_category.extend(garage_door_sensors)

    entity_list = []
    seen_ids = set()  # Track unique IDs to prevent duplicates

    director = entry_data[CONF_DIRECTOR]

    for item in items_of_category:
        try:
            if item["type"] == CONTROL4_ENTITY_TYPE and item["id"]:
                # Skip if this is a relay device (except garage door sensors)
                if item.get("proxy") in CONTROL4_RELAY_PROXY_TYPES:
                    _LOGGER.debug("Skipping relay device: %s", item.get("proxy"))
                    continue

                item_name = str(item["name"])
                item_id = item["id"]
                item_area = item["roomName"]
                item_parent_id = item["parentId"]
                item_proxy = item.get("proxy", "")
                _LOGGER.debug("Processing device: %s (proxy: %s)", item_name, item_proxy)

                # Generate a unique ID that includes all relevant information
                unique_id = f"{entry.entry_id}_{item_id}_{item_proxy}_{item_name}"
                if unique_id in seen_ids:
                    _LOGGER.warning(
                        "Duplicate unique ID detected for %s, skipping", item_name
                    )
                    continue
                seen_ids.add(unique_id)

                item_manufacturer = None
                item_device_name = None
                item_model = None

                item_device_class = BinarySensorDeviceClass.OPENING
                for proxy_type in [
                    CONTROL4_DOOR_PROXY,
                    CONTROL4_WINDOW_PROXY,
                    CONTROL4_MOTION_PROXY,
                    CONTROL4_GARAGE_DOOR_PROXY,
                ]:
                    if item["proxy"] == proxy_type:
                        item_device_class = CONTROL4_PROXY_MAPPING[proxy_type]
                        _LOGGER.debug("Found device class %s for %s", item_device_class, item_name)
                        break

                item_setup_info = await director.getItemSetup(item_id)
                item_setup_info = json.loads(item_setup_info)
                item_alarm_zone_id = None
                if "panel_setup" in item_setup_info:
                    for key in item_setup_info["panel_setup"]["all_zones"]["zone_info"]:
                        if key["name"] == item_name:
                            item_alarm_zone_id = key["id"]
                            break

                for parent_item in items_of_category:
                    if parent_item["id"] == item_parent_id:
                        item_manufacturer = parent_item["manufacturer"]
                        item_device_name = parent_item["name"]
                        item_model = parent_item["model"]
            else:
                continue
        except KeyError:
            _LOGGER.warning(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue

        item_attributes = await director_get_entry_variables(hass, entry, item_id)
        _LOGGER.debug("Device attributes for %s: %s", item_name, item_attributes)

        entity_list.append(
            Control4BinarySensor(
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
                item_device_class,
                item_alarm_zone_id,
                item_proxy,
                unique_id,
            )
        )

    async_add_entities(entity_list, True)


class Control4BinarySensor(Control4Entity, BinarySensorEntity):
    """Control4 alarm control panel entity."""

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
        device_class: str,
        alarm_zone_id: int,
        proxy_type: str,
        unique_id: str,
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
        self._device_class = device_class
        self._proxy_type = proxy_type
        self._extra_state_attributes["alarm_zone_id"] = alarm_zone_id
        self._attr_available = True
        self._attr_unique_id = unique_id
        
        # Initialize state from attributes
        if "ContactState" in self._extra_state_attributes:
            self._extra_state_attributes["ContactState"] = bool(
                self._extra_state_attributes["ContactState"]
            )
        elif "RelayState" in self._extra_state_attributes:
            # For garage door sensors, use RelayState instead of ContactState
            self._extra_state_attributes["ContactState"] = bool(
                self._extra_state_attributes["RelayState"]
            )
            
        self._extra_state_attributes["StateVerified"] = bool(
            self._extra_state_attributes.get("StateVerified", True)
        )

    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket
        update for our item id/parent device id."""

        # Message will be False when a Websocket disconnect is detected
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]
            # Extra handling for alarm specific messages
            if "zone_state" in data:
                self._extra_state_attributes["ContactState"] = bool(
                    not data["zone_state"].pop("is_open")
                )
                self._extra_state_attributes["LastActionTime"] = message["time"]

            if "contact_state" in data:
                self._extra_state_attributes["ContactState"] = bool(
                    data["contact_state"].pop("current_state") == "CLOSED"
                )
                self._extra_state_attributes["StateVerified"] = data[
                    "contact_state"
                ].pop("is_verified")
                self._extra_state_attributes["LastActionTime"] = message["time"]
                await self._data_to_extra_state_attributes(data["contact_state"])

            if "relay_state" in data:
                # For garage door sensors, use relay_state instead of contact_state
                self._extra_state_attributes["ContactState"] = bool(
                    data["relay_state"].pop("current_state") == "CLOSED"
                )
                self._extra_state_attributes["StateVerified"] = data["relay_state"].pop(
                    "is_verified"
                )
                self._extra_state_attributes["LastActionTime"] = message["time"]
                await self._data_to_extra_state_attributes(data["relay_state"])

        _LOGGER.debug("Updated state for %s: %s", self.name, self._extra_state_attributes)
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Return true if the binary sensor is on."""
        # In Control4, True = closed/clear and False = open/not clear
        # For some reason, Control4 gives us ContactState on entity init,
        # but updates STATE when changes occur (the value of ContactState is
        # never updated)
        if "ContactState" in self._extra_state_attributes:
            return not bool(self.extra_state_attributes["ContactState"])
        _LOGGER.warning(
            "ContactState not found in extra_state_attributes: %s",
            str(self._extra_state_attributes),
        )

        return False

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class

    @property
    def device_info(self):
        """Return info of parent Control4 device of entity."""
        # In Control4, binary sensors are not attached to a parent device.
        # Rather, they are attached to a room id.
        # Therefore, there is no device info for Home Assistant to use.
        return None
