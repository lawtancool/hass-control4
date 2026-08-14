"""Platform for Control4 Alarm Control Panel."""

from __future__ import annotations

from functools import cached_property
import logging

from pyControl4.alarm import C4SecurityPanel
import voluptuous

from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
)
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelEntityFeature,
    AlarmControlPanelState,
    CodeFormat,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform

from . import Control4Entity, get_items_of_category
from .alarm_utils import (
    CONTROL4_PARTITION_STATE_VAR,
    is_usable_partition,
    merge_arm_types_into_cache,
    parse_arm_types_from_capabilities,
)
from .const import (
    CONF_ALARM_ARM_STATES,
    CONF_ALARM_AWAY_MODE,
    CONF_ALARM_CUSTOM_BYPASS_MODE,
    CONF_ALARM_HOME_MODE,
    CONF_ALARM_NIGHT_MODE,
    CONF_ALARM_VACATION_MODE,
    CONF_DIRECTOR,
    CONTROL4_ENTITY_TYPE,
    DEFAULT_ALARM_AWAY_MODE,
    DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
    DEFAULT_ALARM_HOME_MODE,
    DEFAULT_ALARM_NIGHT_MODE,
    DEFAULT_ALARM_VACATION_MODE,
    DOMAIN,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

CONTROL4_CATEGORY = "security"

CONTROL4_ARMED_AWAY_VAR = "AWAY_STATE"
CONTROL4_ARMED_HOME_VAR = "HOME_STATE"
CONTROL4_DISARMED_VAR = "DISARMED_STATE"
CONTROL4_ALARM_STATE_VAR = "ALARM_STATE"
CONTROL4_DISPLAY_TEXT_VAR = "DISPLAY_TEXT"
CONTROL4_TROUBLE_TEXT_VAR = "TROUBLE_TEXT"
CONTROL4_DELAY_TIME_REMAINING_VAR = "DELAY_TIME_REMAINING"
CONTROL4_OPEN_ZONE_COUNT_VAR = "OPEN_ZONE_COUNT"
CONTROL4_ALARM_TYPE_VAR = "ALARM_TYPE"
CONTROL4_ARMED_TYPE_VAR = "ARMED_TYPE"
CONTROL4_LAST_EMERGENCY_VAR = "LAST_EMERGENCY"
CONTROL4_LAST_ARM_FAILURE_VAR = "LAST_ARM_FAILED"

CONTROL4_EXIT_DELAY_STATE = "EXIT_DELAY"
CONTROL4_ENTRY_DELAY_STATE = "ENTRY_DELAY"
CONTROL4_ARMED_STATE = "ARMED"
CONTROL4_ARMED_HOME_STATE = "ARMED_HOME"
CONTROL4_ARMED_AWAY_STATE = "ARMED_AWAY"
CONTROL4_DISARMED_NOT_READY_STATE = "DISARMED_NOT_READY"
CONTROL4_DISARMED_READY_STATE = "DISARMED_READY"

CONTROL4_PARTITION_STATE_DATA_MAPPING = {
    "state": CONTROL4_PARTITION_STATE_VAR,
    "trouble": "TROUBLE_TEXT",
    "text": "DISPLAY_TEXT",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """Set up Control4 alarm control panel from a config entry."""
    platform = entity_platform.current_platform.get()
    if platform is not None:
        platform.async_register_entity_service(
            "send_alarm_keystrokes",
            {voluptuous.Required("keystrokes"): cv.string},
            "send_alarm_keystrokes",
        )
        platform.async_register_entity_service(
            "trigger_emergency",
            {voluptuous.Required("emergency_type"): cv.string},
            "async_trigger_emergency",
        )

    entry_data = hass.data[DOMAIN][entry.entry_id]
    items_of_category = await get_items_of_category(hass, entry, CONTROL4_CATEGORY)
    entity_list = []
    director = entry_data[CONF_DIRECTOR]

    for item in items_of_category:
        try:
            if item["type"] != CONTROL4_ENTITY_TYPE or not item["id"]:
                continue

            item_name = str(item["name"])
            item_id = item["id"]
            item_area = item["roomName"]
            item_parent_id = item["parentId"]
            item_manufacturer = None
            item_device_name = None
            item_model = None

            capabilities = item.get("capabilities", {})
            cap_arm_types = parse_arm_types_from_capabilities(capabilities)
            merge_arm_types_into_cache(entry_data[CONF_ALARM_ARM_STATES], cap_arm_types)

            try:
                item_setup_info = await director.get_item_setup(item_id)
                item_enabled = item_setup_info.get("setup", {}).get("enabled", True)
            except (KeyError, TypeError):
                _LOGGER.debug(
                    "No setup info available for device %s, defaulting to enabled",
                    item_name,
                )
                item_enabled = True

            for parent_item in items_of_category:
                if parent_item["id"] == item_parent_id:
                    item_manufacturer = parent_item.get("manufacturer")
                    item_device_name = parent_item.get("name")
                    item_model = parent_item.get("model")
        except KeyError as exception:
            _LOGGER.debug(
                "Unknown device properties received from Control4: %s %s",
                exception,
                item,
            )
            continue

        item_attributes = await director_get_entry_variables(hass, entry, item_id)
        c4_alarm = C4SecurityPanel(director, item_id)
        item_arm_types = await c4_alarm.get_arm_types()
        if not item_arm_types:
            item_arm_types = cap_arm_types
        merge_arm_types_into_cache(entry_data[CONF_ALARM_ARM_STATES], item_arm_types)

        item_emergency_types = await c4_alarm.get_emergency_types()
        usable = is_usable_partition(item_attributes, item_arm_types)

        entity_list.append(
            Control4AlarmControlPanel(
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
                item_enabled and usable,
                item_emergency_types,
                item_arm_types,
                usable,
            )
        )

    async_add_entities(entity_list, True)


class Control4AlarmControlPanel(Control4Entity, AlarmControlPanelEntity):  # type: ignore[misc]
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
        is_enabled: bool,
        emergency_types: list[str],
        arm_types: list[str],
        is_usable: bool,
    ) -> None:
        """Initialize Control4 alarm control panel entity."""
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
        self._is_enabled = is_enabled
        self._is_usable = is_usable
        self._emergency_types = emergency_types
        self._arm_types = arm_types
        self._extra_state_attributes["zone_state"] = {}
        if arm_types:
            self._extra_state_attributes["arm_types"] = arm_types
        if emergency_types:
            self._extra_state_attributes["emergency_types"] = emergency_types

    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update for our item id/parent device id."""
        _LOGGER.debug(message)

        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]
            if "partition_state" in data:
                data = data["partition_state"]
                for key, value in data.items():
                    if key in CONTROL4_PARTITION_STATE_DATA_MAPPING:
                        self._extra_state_attributes[
                            CONTROL4_PARTITION_STATE_DATA_MAPPING[key]
                        ] = value
                    else:
                        self._extra_state_attributes[key.upper()] = value
            elif "text" in data:
                self._extra_state_attributes[
                    CONTROL4_PARTITION_STATE_DATA_MAPPING["text"]
                ] = data["text"]
            elif "zone_state" in data:
                data = data["zone_state"]
                self._extra_state_attributes["zone_state"][data["id"]] = data
            elif "devicecommand" in data:
                data = data["devicecommand"]["params"]
                await self._data_to_extra_state_attributes(data)
            else:
                await self._data_to_extra_state_attributes(data)
        _LOGGER.debug("Message for device %s", device)
        self.async_write_ha_state()

    def create_api_object(self):
        """Create a pyControl4 device object."""
        return C4SecurityPanel(self.entry_data[CONF_DIRECTOR], self._idx)

    @cached_property
    def entity_registry_enabled_default(self) -> bool:
        """Return if the entity should be enabled when first added to the entity registry."""
        return self._is_enabled

    @cached_property
    def code_format(self):
        """Regex for code format or None if no code is required."""
        return CodeFormat.NUMBER

    @cached_property
    def supported_features(self) -> AlarmControlPanelEntityFeature:
        """Flag supported features."""
        flags = AlarmControlPanelEntityFeature(0)
        if not self.entry_data[CONF_ALARM_AWAY_MODE] == DEFAULT_ALARM_AWAY_MODE:
            flags |= AlarmControlPanelEntityFeature.ARM_AWAY
        if not self.entry_data[CONF_ALARM_HOME_MODE] == DEFAULT_ALARM_HOME_MODE:
            flags |= AlarmControlPanelEntityFeature.ARM_HOME
        if not self.entry_data[CONF_ALARM_NIGHT_MODE] == DEFAULT_ALARM_NIGHT_MODE:
            flags |= AlarmControlPanelEntityFeature.ARM_NIGHT
        if (
            not self.entry_data[CONF_ALARM_CUSTOM_BYPASS_MODE]
            == DEFAULT_ALARM_CUSTOM_BYPASS_MODE
        ):
            flags |= AlarmControlPanelEntityFeature.ARM_CUSTOM_BYPASS
        if not self.entry_data[CONF_ALARM_VACATION_MODE] == DEFAULT_ALARM_VACATION_MODE:
            flags |= AlarmControlPanelEntityFeature.ARM_VACATION
        if self._emergency_types:
            flags |= AlarmControlPanelEntityFeature.TRIGGER
        return flags

    def _partition_state_value(self) -> str | None:
        """Return partition state from PARTITION_STATE or websocket 'state' attr."""
        attrs = self.extra_state_attributes
        partition = attrs.get(CONTROL4_PARTITION_STATE_VAR)
        if partition:
            return str(partition)
        raw = attrs.get("state")
        if raw:
            return str(raw)
        return None

    def _is_triggered(self) -> bool:
        """Return True when the panel reports an active alarm."""
        attrs = self.extra_state_attributes
        alarm_flag = attrs.get(CONTROL4_ALARM_STATE_VAR)
        if alarm_flag is not None and str(alarm_flag) not in ("0", "", "False", "false"):
            try:
                if int(alarm_flag) == 1:
                    return True
            except (TypeError, ValueError):
                if str(alarm_flag).lower() in ("true", "yes", "on"):
                    return True
        alarm_type = attrs.get(CONTROL4_ALARM_TYPE_VAR)
        return bool(alarm_type and str(alarm_type).strip())

    def _armed_state_from_type(self, armed_type: str | None) -> AlarmControlPanelState | None:
        """Map Control4 armed type string to HA alarm state."""
        if not armed_type:
            return None
        if armed_type == self.entry_data[CONF_ALARM_AWAY_MODE]:
            return AlarmControlPanelState.ARMED_AWAY
        if armed_type == self.entry_data[CONF_ALARM_HOME_MODE]:
            return AlarmControlPanelState.ARMED_HOME
        if armed_type == self.entry_data[CONF_ALARM_NIGHT_MODE]:
            return AlarmControlPanelState.ARMED_NIGHT
        if armed_type == self.entry_data[CONF_ALARM_CUSTOM_BYPASS_MODE]:
            return AlarmControlPanelState.ARMED_CUSTOM_BYPASS
        if armed_type == self.entry_data[CONF_ALARM_VACATION_MODE]:
            return AlarmControlPanelState.ARMED_VACATION
        return None

    def _armed_state_from_partition(self, partition_state: str) -> AlarmControlPanelState | None:
        """Map partition state that embeds arm mode."""
        armed_type = self.extra_state_attributes.get(CONTROL4_ARMED_TYPE_VAR)
        mapped = self._armed_state_from_type(
            str(armed_type) if armed_type else None
        )
        if mapped:
            return mapped

        if partition_state == CONTROL4_ARMED_AWAY_STATE:
            return AlarmControlPanelState.ARMED_AWAY
        if partition_state == CONTROL4_ARMED_HOME_STATE:
            return AlarmControlPanelState.ARMED_HOME
        if partition_state == CONTROL4_ARMED_STATE:
            return AlarmControlPanelState.ARMED_AWAY

        lowered = partition_state.lower()
        for option_key, ha_state in (
            (CONF_ALARM_AWAY_MODE, AlarmControlPanelState.ARMED_AWAY),
            (CONF_ALARM_HOME_MODE, AlarmControlPanelState.ARMED_HOME),
            (CONF_ALARM_NIGHT_MODE, AlarmControlPanelState.ARMED_NIGHT),
            (CONF_ALARM_CUSTOM_BYPASS_MODE, AlarmControlPanelState.ARMED_CUSTOM_BYPASS),
            (CONF_ALARM_VACATION_MODE, AlarmControlPanelState.ARMED_VACATION),
        ):
            mode_name = self.entry_data.get(option_key)
            if mode_name and mode_name.lower() in lowered:
                return ha_state
        return None

    def _armed_state_from_flags(self) -> AlarmControlPanelState | None:
        """Fallback using HOME_STATE / AWAY_STATE / DISARMED_STATE flags."""
        attrs = self.extra_state_attributes

        def _flag(name: str) -> bool:
            value = attrs.get(name)
            if value is None:
                return False
            try:
                return int(value) == 1
            except (TypeError, ValueError):
                return str(value).lower() in ("true", "yes", "on", "1")

        if _flag(CONTROL4_DISARMED_VAR):
            return AlarmControlPanelState.DISARMED
        if _flag(CONTROL4_ARMED_HOME_VAR):
            return AlarmControlPanelState.ARMED_HOME
        if _flag(CONTROL4_ARMED_AWAY_VAR):
            return AlarmControlPanelState.ARMED_AWAY
        return None

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:  # type: ignore[override]
        """Return the state of the device."""
        if self._is_triggered():
            return AlarmControlPanelState.TRIGGERED

        partition_state = self._partition_state_value()
        if partition_state == CONTROL4_EXIT_DELAY_STATE:
            return AlarmControlPanelState.ARMING
        if partition_state == CONTROL4_ENTRY_DELAY_STATE:
            return AlarmControlPanelState.PENDING
        if partition_state in (
            CONTROL4_DISARMED_NOT_READY_STATE,
            CONTROL4_DISARMED_READY_STATE,
        ):
            return AlarmControlPanelState.DISARMED

        if partition_state and "ARMED" in partition_state:
            armed = self._armed_state_from_partition(partition_state)
            if armed:
                return armed

        flag_state = self._armed_state_from_flags()
        if flag_state is not None:
            return flag_state

        return None

    async def _async_refresh_panel_state(self) -> None:
        """Poll director for partition/armed state after a command."""
        c4_alarm = self.create_api_object()
        try:
            partition = await c4_alarm.get_partition_state()
            if partition:
                self._extra_state_attributes[CONTROL4_PARTITION_STATE_VAR] = partition
            armed_type = await c4_alarm.get_armed_type()
            if armed_type is not None:
                self._extra_state_attributes[CONTROL4_ARMED_TYPE_VAR] = armed_type
            alarm_active = await c4_alarm.get_alarm_state()
            if alarm_active is not None:
                self._extra_state_attributes[CONTROL4_ALARM_STATE_VAR] = int(alarm_active)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Failed to refresh alarm panel state for %s", self._idx)
        self.async_write_ha_state()

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.set_arm(code or "", self.entry_data[CONF_ALARM_AWAY_MODE])
        await self._async_refresh_panel_state()

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.set_arm(code or "", self.entry_data[CONF_ALARM_HOME_MODE])
        await self._async_refresh_panel_state()

    async def async_alarm_arm_night(self, code=None):
        """Send arm night command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.set_arm(code or "", self.entry_data[CONF_ALARM_NIGHT_MODE])
        await self._async_refresh_panel_state()

    async def async_alarm_arm_custom_bypass(self, code=None):
        """Send arm custom bypass command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.set_arm(code or "", self.entry_data[CONF_ALARM_CUSTOM_BYPASS_MODE])
        await self._async_refresh_panel_state()

    async def async_alarm_arm_vacation(self, code=None):
        """Send arm vacation command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.set_arm(code or "", self.entry_data[CONF_ALARM_VACATION_MODE])
        await self._async_refresh_panel_state()

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        c4_alarm = self.create_api_object()
        await c4_alarm.set_disarm(code or "")
        await self._async_refresh_panel_state()

    async def async_alarm_trigger(self, code=None):
        """Send trigger/emergency command."""
        if not self._emergency_types:
            return
        c4_alarm = self.create_api_object()
        preferred_order = ["Police", "Fire", "Medical", "Panic"]
        emergency_type = next(
            (t for t in preferred_order if t in self._emergency_types),
            self._emergency_types[0],
        )
        await c4_alarm.trigger_emergency(emergency_type)
        await self._async_refresh_panel_state()

    async def async_trigger_emergency(self, emergency_type: str) -> None:
        """Trigger a specific emergency type supported by this panel."""
        if emergency_type not in self._emergency_types:
            _LOGGER.warning(
                "Emergency type %s not supported on %s (available: %s)",
                emergency_type,
                self.entity_id,
                self._emergency_types,
            )
            return
        c4_alarm = self.create_api_object()
        await c4_alarm.trigger_emergency(emergency_type)
        await self._async_refresh_panel_state()

    async def send_alarm_keystrokes(self, keystrokes):
        """Send custom keystrokes."""
        c4_alarm = self.create_api_object()
        for key in keystrokes:
            await c4_alarm.send_key_press(key)
        await self._async_refresh_panel_state()
