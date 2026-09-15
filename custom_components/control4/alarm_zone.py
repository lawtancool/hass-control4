"""Expose Control4 alarm zones as optional, read-only binary sensors."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import (
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_WEBSOCKET,
    CONTROL4_ENTITY_TYPE,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)


def zone_rows(setup):
    """Index valid zone records; a missing state must never mean clear."""
    rows = setup.get("panel_setup", {}).get("all_zones", {}).get("zone_info", [])
    if rows is None:
        return {}
    if isinstance(rows, dict):
        rows = [rows]
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            zone_id = int(row["id"])
        except (KeyError, ValueError, TypeError):
            continue
        result[zone_id] = dict(row)
    return result


def zone_open(row):
    """Keep unknown states unavailable instead of treating them as closed."""
    value = row.get("open") if row else None
    return value if isinstance(value, bool) else None


def zone_event(message, zone_id):
    """Return a matching zone's explicit state without modifying the event."""
    if not isinstance(message, dict) or message.get("evtName") != "OnDataToUI":
        return None
    data = message.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("zone_state"), dict):
        return None
    zone = data["zone_state"]
    try:
        matches = int(zone.get("id")) == zone_id
    except (ValueError, TypeError):
        return None
    value = zone.get("is_open")
    return value if matches and isinstance(value, bool) else None


async def async_setup_alarm_zones(hass, entry, async_add_entities):
    """Discover zones independently of the standalone sensors category."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    panels = {
        item["id"]: item
        for item in entry_data[CONF_DIRECTOR_ALL_ITEMS]
        if item.get("type") == CONTROL4_ENTITY_TYPE
        and item.get("proxy") == "securitypanel"
    }
    entities = []
    for panel_id, panel in panels.items():

        async def refresh(panel_id=panel_id):
            try:
                setup = await entry_data[CONF_DIRECTOR].get_item_setup(panel_id)
                return zone_rows(setup)
            except Exception as error:
                # This optional platform must not prevent standalone sensors loading.
                raise UpdateFailed("Unable to read Control4 alarm zones") from error

        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"Control4 panel {panel_id} zones",
            update_method=refresh,
            update_interval=timedelta(seconds=5),
        )
        await coordinator.async_refresh()
        if not coordinator.last_update_success:
            continue
        for zone_id, zone in coordinator.data.items():
            entities.append(
                Control4AlarmZone(coordinator, entry_data, panel, zone_id, zone)
            )
    async_add_entities(entities)


class Control4AlarmZone(CoordinatorEntity, BinarySensorEntity):
    """An alarm-zone state, with live events and periodic resynchronization."""

    # Some zones already have standalone sensors. Users enable only the extras needed.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry_data, panel, zone_id, zone):
        super().__init__(coordinator)
        self._entry_data = entry_data
        self._panel = panel
        self._zone_id = zone_id
        self._attr_name = zone.get("name") or f"Zone {zone_id}"
        self._attr_unique_id = f"{entry_data[CONF_CONTROLLER_UNIQUE_ID]}_panel_{panel['id']}_zone_{zone_id}"
        self._attr_device_info = {"identifiers": {(DOMAIN, str(panel["parentId"]))}}
        self._attr_extra_state_attributes = {
            "alarm_zone_id": zone_id,
            "control4_panel_id": panel["id"],
            "zone_type": zone.get("type"),
        }
        if zone.get("type") == 5:
            self._attr_device_class = BinarySensorDeviceClass.MOTION
        self._callback_ids = {panel["id"], panel["parentId"]}

    @property
    def is_on(self):
        return zone_open((self.coordinator.data or {}).get(self._zone_id))

    @property
    def available(self):
        return super().available and self.is_on is not None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        websocket = self._entry_data[CONF_WEBSOCKET]
        for item_id in self._callback_ids:
            await self.hass.async_add_executor_job(
                websocket.add_item_callback, item_id, self._zone_callback
            )

    async def async_will_remove_from_hass(self):
        websocket = self._entry_data[CONF_WEBSOCKET]
        for item_id in self._callback_ids:
            websocket.remove_item_callback(item_id, self._zone_callback)
        await super().async_will_remove_from_hass()

    async def _zone_callback(self, device, message):
        if message is False:
            self.coordinator.async_set_update_error(
                UpdateFailed("Control4 disconnected")
            )
            return
        state = zone_event(message, self._zone_id)
        if state is None:
            return
        # A single fresh event must not revive stale sibling zones after a failure.
        rows = (
            dict(self.coordinator.data or {})
            if self.coordinator.last_update_success
            else {}
        )
        rows[self._zone_id] = {
            **rows.get(self._zone_id, {}),
            "id": self._zone_id,
            "open": state,
        }
        if self.coordinator.last_update_success:
            # Keep the periodic resync deadline: push updates must not postpone it.
            self.coordinator.data = rows
            self.coordinator.async_update_listeners()
        else:
            self.coordinator.async_set_updated_data(rows)
