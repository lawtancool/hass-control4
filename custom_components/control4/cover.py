"""Platform for Control4 Covers (blinds/shades and garage doors)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pyControl4.blind import C4Blind

from . import Control4Entity
from .const import (
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONTROL4_ENTITY_TYPE,
    DOMAIN,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

# Substrings commonly found in Control4 proxy identifiers for window coverings
_COVER_PROXY_SUBSTRINGS = (
    "shade",
    "blind",
    "windowcover",
    "curtain",
    "drap",
)

CONTROL4_GARAGE_DOOR_PROXY = "relaycontact_garagedoor_c4"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Control4 covers from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    all_items: list[dict[str, Any]] = entry_data[CONF_DIRECTOR_ALL_ITEMS]

    # Build quick lookup by id for parent data
    items_by_id = {item.get("id"): item for item in all_items if "id" in item}

    def _is_cover_proxy(proxy_value: str | None) -> bool:
        if not proxy_value or not isinstance(proxy_value, str):
            return False
        p = proxy_value.lower()
        return any(s in p for s in _COVER_PROXY_SUBSTRINGS)

    # Identify blind/shade cover entities via proxy type heuristics
    cover_items: list[dict[str, Any]] = [
        item
        for item in all_items
        if item.get("type") == CONTROL4_ENTITY_TYPE
        and item.get("id")
        and _is_cover_proxy(item.get("proxy"))
    ]

    garage_items: list[dict[str, Any]] = [
        item
        for item in all_items
        if item.get("type") == CONTROL4_ENTITY_TYPE
        and item.get("id")
        and item.get("proxy") == CONTROL4_GARAGE_DOOR_PROXY
    ]

    entity_list: list[CoverEntity] = []

    for item in cover_items:
        try:
            item_name = str(item["name"])
            item_id = item["id"]
            item_area = item.get("roomName")
            item_parent_id = item["parentId"]

            item_manufacturer = None
            item_device_name = None
            item_model = None

            parent = items_by_id.get(item_parent_id)
            if parent:
                item_manufacturer = parent.get("manufacturer")
                item_device_name = parent.get("name")
                item_model = parent.get("model")
        except KeyError:
            _LOGGER.exception(
                "Unknown device properties received from Control4: %s",
                item,
            )
            continue

        item_attributes = await director_get_entry_variables(hass, entry, item_id)

        entity_list.append(
            Control4Cover(
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

    for item in garage_items:
        try:
            item_name = str(item["name"])
            item_id = item["id"]
            item_area = item.get("roomName")
            item_parent_id = item["parentId"]

            # Each garage door is its own HA device (parent is a room, shared by all doors).
            item_manufacturer = item.get("manufacturer") or "Generic"
            item_device_name = item_name
            item_model = item.get("model") or "Garage Door (Sensor)"
        except KeyError:
            _LOGGER.exception(
                "Unknown garage door properties received from Control4: %s",
                item,
            )
            continue

        item_attributes = await director_get_entry_variables(hass, entry, item_id)

        entity_list.append(
            Control4GarageCover(
                entry_data,
                entry,
                item_name,
                item_id,
                item_device_name,
                item_manufacturer,
                item_model,
                item_id,
                item_area,
                item_attributes,
                item_parent_id,
            )
        )

    async_add_entities(entity_list, True)


class Control4Cover(Control4Entity, CoverEntity):  # type: ignore[misc]
    """Control4 cover (blinds/shades) entity."""

    _attr_assumed_state = True
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.STOP
    )

    def create_api_object(self) -> C4Blind:
        """Create a pyControl4 device object.

        This exists so the director token used is always the latest one,
        without needing to re-init the entire entity.
        """
        return C4Blind(self.entry_data[CONF_DIRECTOR], self._idx)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

    @property
    def current_cover_position(self) -> int | None:  # type: ignore[override]
        """Unknown in stateless mode to keep both buttons enabled."""
        return None

    @property
    def is_closed(self) -> bool | None:  # type: ignore[override]
        """Unknown in stateless mode to keep both buttons enabled."""
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        c4_blind = self.create_api_object()
        await c4_blind.open()

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        c4_blind = self.create_api_object()
        await c4_blind.close()

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """No-op in stateless mode (no position slider)."""
        return

    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop the cover."""
        c4_blind = self.create_api_object()
        await c4_blind.stop()


class Control4GarageCover(Control4Entity, CoverEntity):  # type: ignore[misc]
    """Control4 garage door (relaycontact_garagedoor_c4) cover entity."""

    _attr_device_class = CoverDeviceClass.GARAGE
    _attr_supported_features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

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
        device_area: str | None,
        device_attributes: dict,
        room_parent_id: int | None = None,
    ) -> None:
        """Initialize garage cover and normalize RelayState into ContactState."""
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
        self._room_parent_id = room_parent_id
        self._attr_available = True
        # Control4 item id used to correlate with binary_sensor (diagnostic).
        self._extra_state_attributes["garage_id"] = idx
        # Keep room id visible even though device_id is the door item itself.
        if room_parent_id is not None:
            self._extra_state_attributes["parent item id"] = room_parent_id
        # Same polarity as binary_sensor.garage_door_*: RelayState 1/True = closed.
        if "RelayState" in self._extra_state_attributes:
            self._apply_closed(bool(int(self._extra_state_attributes["RelayState"])))
        elif "ContactState" in self._extra_state_attributes:
            self._apply_closed(bool(self._extra_state_attributes["ContactState"]))

    async def async_added_to_hass(self) -> None:
        """Register director callbacks; optionally note matching binary_sensor."""
        await super().async_added_to_hass()
        # Diagnostic only — open/closed state comes from Control4, not this link.
        linked = self._resolve_binary_entity_id()
        if linked:
            self._extra_state_attributes["linked_binary"] = linked
            self.async_write_ha_state()

    def _resolve_binary_entity_id(self) -> str | None:
        """Find binary_sensor sharing this Control4 item id (garage_id)."""
        garage_id = int(self._idx)
        for state in self.hass.states.async_all("binary_sensor"):
            raw = state.attributes.get("garage_id", state.attributes.get("item id"))
            try:
                if raw is not None and int(raw) == garage_id:
                    return state.entity_id
            except (TypeError, ValueError):
                continue
        return None

    def _apply_closed(self, closed: bool) -> None:
        """Set CoverEntity closed flag and matching attributes."""
        self._attr_is_closed = closed
        self._extra_state_attributes["ContactState"] = closed
        self._extra_state_attributes["RelayState"] = int(closed)

    async def _send_command(self, command: str) -> None:
        """Send OPEN/CLOSE to the Control4 director item.

        Do not poll director RelayState afterward — mid-travel reads are often
        stale and overwrite correct websocket ContactState updates.
        """
        director = self.entry_data[CONF_DIRECTOR]
        await director.send_post_request(
            f"/api/v1/items/{self._idx}/commands",
            command,
            {},
        )

    async def _update_callback(self, device, message):
        """Update closed state from Control4 websocket relay_state."""
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message.get("data") or {}
            if "relay_state" in data and isinstance(data["relay_state"], dict):
                # Copy — binary_sensor also handles this shared mutable payload.
                relay_state = dict(data["relay_state"])
                current = relay_state.get("current_state")
                if current is not None:
                    self._apply_closed(current == "CLOSED")
                verified = relay_state.get("is_verified")
                if verified is not None:
                    self._extra_state_attributes["StateVerified"] = verified
                if "time" in message:
                    self._extra_state_attributes["LastActionTime"] = message["time"]
        self.async_write_ha_state()

    @property
    def is_closed(self) -> bool | None:  # type: ignore[override]
        """Return True when the garage door is closed."""
        if self._attr_is_closed is not None:
            return self._attr_is_closed
        if "ContactState" in self._extra_state_attributes:
            return bool(self._extra_state_attributes["ContactState"])
        if "RelayState" in self._extra_state_attributes:
            return bool(int(self._extra_state_attributes["RelayState"]))
        return None

    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the garage door."""
        await self._send_command("OPEN")

    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the garage door."""
        await self._send_command("CLOSE")
