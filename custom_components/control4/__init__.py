"""The Control4 integration."""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from functools import cached_property
from typing import Any
import random

from aiohttp import client_exceptions
from custom_components.control4.config_flow import CannotConnect
from pyControl4.account import C4Account
from pyControl4.director import C4Director
from pyControl4.error_handling import BadCredentials, InvalidCategory
from pyControl4.websocket import C4Websocket

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
    Platform,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import aiohttp_client, device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .const import (
    CONF_ACCOUNT,
    CONF_ALARM_ARM_STATES,
    CONF_ALARM_AWAY_MODE,
    CONF_ALARM_CUSTOM_BYPASS_MODE,
    CONF_ALARM_HOME_MODE,
    CONF_ALARM_NIGHT_MODE,
    CONF_ALARM_VACATION_MODE,
    CONF_CANCEL_TOKEN_REFRESH_CALLBACK,
    CONF_CONFIG_LISTENER,
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_DIRECTOR_MODEL,
    CONF_DIRECTOR_SW_VERSION,
    CONF_WEBSOCKET,
    CONF_UI_CONFIGURATION,
    DEFAULT_ALARM_AWAY_MODE,
    DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
    DEFAULT_ALARM_HOME_MODE,
    DEFAULT_ALARM_NIGHT_MODE,
    DEFAULT_ALARM_VACATION_MODE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    RETRY_BACKOFF_MAX_SEC,
    SCHEDULE_REFRESH_ADVANCE_SEC,
)
from .director_utils import director_get_entry_variables

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.LIGHT,
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.LOCK,
    Platform.MEDIA_PLAYER,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.FAN,
    Platform.CLIMATE,
    Platform.COVER,
]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Control4 from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry.entry_id, {})
    config = entry.data

    await refresh_tokens(hass, entry)
    # Copy controller unique id from config to entry_data for use by entities
    entry_data[CONF_CONTROLLER_UNIQUE_ID] = config[CONF_CONTROLLER_UNIQUE_ID]

    # Add Control4 controller to device registry
    try:
        controller_href = (await entry_data[CONF_ACCOUNT].get_account_controllers())[
            "href"
        ]
    except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
        raise ConfigEntryNotReady(exception) from exception

    try:
        entry_data[CONF_DIRECTOR_SW_VERSION] = await entry_data[
            CONF_ACCOUNT
        ].get_controller_os_version(controller_href)
    except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
        raise ConfigEntryNotReady(exception) from exception

    _, model, mac_address = entry_data[CONF_CONTROLLER_UNIQUE_ID].split("_", 3)
    entry_data[CONF_DIRECTOR_MODEL] = model.upper()

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry_data[CONF_CONTROLLER_UNIQUE_ID])},
        connections={(dr.CONNECTION_NETWORK_MAC, mac_address)},
        manufacturer="Control4",
        name=entry_data[CONF_CONTROLLER_UNIQUE_ID],
        model=entry_data[CONF_DIRECTOR_MODEL],
        sw_version=entry_data[CONF_DIRECTOR_SW_VERSION],
    )

    # Store all items found on controller for platforms to use
    try:
        director_all_items = await entry_data[CONF_DIRECTOR].get_all_item_info()
    except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
        raise ConfigEntryNotReady(exception) from exception
    entry_data[CONF_DIRECTOR_ALL_ITEMS] = director_all_items

    entry_data[CONF_UI_CONFIGURATION] = await entry_data[CONF_DIRECTOR].get_ui_configuration()

    # Load options from config entry
    entry_data[CONF_SCAN_INTERVAL] = entry.options.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )

    # Load options from config entry
    entry_data[CONF_ALARM_AWAY_MODE] = entry.options.get(
        CONF_ALARM_AWAY_MODE, DEFAULT_ALARM_AWAY_MODE
    )
    entry_data[CONF_ALARM_HOME_MODE] = entry.options.get(
        CONF_ALARM_HOME_MODE, DEFAULT_ALARM_HOME_MODE
    )
    entry_data[CONF_ALARM_NIGHT_MODE] = entry.options.get(
        CONF_ALARM_NIGHT_MODE, DEFAULT_ALARM_NIGHT_MODE
    )
    entry_data[CONF_ALARM_CUSTOM_BYPASS_MODE] = entry.options.get(
        CONF_ALARM_CUSTOM_BYPASS_MODE, DEFAULT_ALARM_CUSTOM_BYPASS_MODE
    )
    entry_data[CONF_ALARM_VACATION_MODE] = entry.options.get(
        CONF_ALARM_VACATION_MODE, DEFAULT_ALARM_VACATION_MODE
    )

    entry_data[CONF_ALARM_ARM_STATES] = {
        DEFAULT_ALARM_AWAY_MODE,
        DEFAULT_ALARM_HOME_MODE,
        DEFAULT_ALARM_NIGHT_MODE,
        DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
        DEFAULT_ALARM_VACATION_MODE,
    }

    entry_data[CONF_CONFIG_LISTENER] = entry.add_update_listener(update_listener)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    entry_data = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug("Disconnecting C4Websocket for config entry unload")
    await entry_data[CONF_WEBSOCKET].sio_disconnect()
    _LOGGER.debug("Cancelling scheduled token refresh for config entry unload")
    entry_data[CONF_CANCEL_TOKEN_REFRESH_CALLBACK]()

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
        _LOGGER.debug("Unloaded entry for %s", entry.entry_id)

    return unload_ok


async def update_listener(hass, config_entry):
    """Update when config_entry options update."""
    _LOGGER.debug("Config entry was updated, rerunning setup")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def get_items_of_category(hass: HomeAssistant, entry: ConfigEntry, category: str):
    """Return a list of all Control4 items with the specified category."""
    _LOGGER.debug("Getting items of category: %s", category)
    director = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR]
    try:
        return_list = await director.get_all_items_by_category(category)
        return return_list
    except InvalidCategory as e:
        _LOGGER.warning(
            "Category %s does not exist on this Control4 system, \
                        entities from this domain will not be setup.",
            category,
            exc_info=True,
        )
        return []


async def refresh_tokens(hass: HomeAssistant, entry: ConfigEntry):
    """Store updated authentication and director tokens in hass.data, and schedule next token refresh."""
    config = entry.data
    verify_ssl_session = aiohttp_client.async_get_clientsession(hass)

    account = C4Account(
        config[CONF_USERNAME], config[CONF_PASSWORD], verify_ssl_session
    )
    try:
        await account.get_account_bearer_token()
    except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
        raise ConfigEntryNotReady(exception) from exception
    except BadCredentials as exception:
        raise ConfigEntryAuthFailed(exception) from exception

    controller_unique_id = config[CONF_CONTROLLER_UNIQUE_ID]
    try:
        director_token_dict = await account.get_director_bearer_token(controller_unique_id)
    except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
        raise ConfigEntryNotReady(exception) from exception
    no_verify_ssl_session = aiohttp_client.async_get_clientsession(
        hass, verify_ssl=False
    )

    refresh_tokens_obj = RefreshTokensObject(hass, entry)
    resetting_client_session = C4ResettingClientSession(
        hass,
        entry,
        refresh_tokens_obj,
        no_verify_ssl_session
    )

    director = C4Director(
        config[CONF_HOST], director_token_dict[CONF_TOKEN], resetting_client_session
    )

    _LOGGER.debug("Saving new account and director tokens in hass data")
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entry_data[CONF_ACCOUNT] = account
    entry_data[CONF_DIRECTOR] = director

    if not (
        CONF_WEBSOCKET in entry_data
        and isinstance(entry_data[CONF_WEBSOCKET], C4Websocket)
    ):
        _LOGGER.debug("First time setup, creating new C4Websocket object")
        connection_tracker = C4WebsocketConnectionTracker(hass, entry)
        websocket = C4Websocket(
            config[CONF_HOST],
            no_verify_ssl_session,
            connection_tracker.connect_callback,
            connection_tracker.disconnect_callback,
        )
        entry_data[CONF_WEBSOCKET] = websocket

        # Silence C4Websocket related loggers, that would otherwise spam INFO logs with debugging messages
        logging.getLogger("socketio.client").setLevel(logging.WARNING)
        logging.getLogger("engineio.client").setLevel(logging.WARNING)
        logging.getLogger("charset_normalizer").setLevel(logging.ERROR)

    _LOGGER.debug("Starting new WebSocket connection")
    try:
        await entry_data[CONF_WEBSOCKET].sio_connect(director.director_bearer_token)
    except Exception as exception:
        raise ConfigEntryNotReady(exception) from exception

    # Schedule refresh 5mins before expiry, but no sooner than 5mins from now
    delay = max(
        director_token_dict["validSeconds"] - SCHEDULE_REFRESH_ADVANCE_SEC,
        SCHEDULE_REFRESH_ADVANCE_SEC,
    )

    _LOGGER.debug(
        "Registering next token refresh in %s seconds",
        delay,
    )
    entry_data[CONF_CANCEL_TOKEN_REFRESH_CALLBACK] = async_call_later(
        hass=hass,
        delay=delay,
        action=refresh_tokens_obj.refresh_tokens,
    )


class C4WebsocketConnectionTracker:
    """Object that provides callables to manually refresh entity states if the Control4 Websocket is disconnected/reconnected."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the state of the connection tracker object."""
        self.hass = hass
        self.entry = entry

        self._was_disconnected = False

    async def connect_callback(self) -> None:
        """Manually refresh entity states when the Websocket is reconnected after a connection drop."""
        if not self._was_disconnected:
            return

        _LOGGER.info("Websocket connection to Control4 reestablished")

        # Refresh state of entities so they are not unavailable anymore
        item_callbacks = self.hass.data[DOMAIN][self.entry.entry_id][
            CONF_WEBSOCKET
        ].item_callbacks
        for item_id, callback in item_callbacks.items():
            item_attributes = await director_get_entry_variables(
                self.hass, self.entry, item_id
            )
            message = {
                "evtName": "OnDataToUI",
                "iddevice": item_id,
                "data": item_attributes,
            }
            await callback(item_id, message)

        self._was_disconnected = False

    async def disconnect_callback(self) -> None:
        """Detect a Websocket connection loss."""
        _LOGGER.warning(
            "Websocket connection to Control4 lost, attempting reconnection"
        )
        self._was_disconnected = True

        # Set all entities to unavailable
        item_callbacks = self.hass.data[DOMAIN][self.entry.entry_id][
            CONF_WEBSOCKET
        ].item_callbacks
        for item_id, callback in item_callbacks.items():
            await callback(item_id, False)


class RefreshTokensObject:
    """Object that provides a callable to refresh tokens."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize a RefreshTokensObject by storing the HomeAssistant and ConfigEntry objects required to run refresh_tokens()."""
        self.hass = hass
        self.entry = entry
        self.retries = 0
        self._lock = asyncio.Lock()
        self._refresh_triggered = False

    async def _get_refreshing_lock(self) -> bool:
        """Get the lock for refreshing tokens. This ensures that only one refresh_tokens() call is running at a time."""
        async with self._lock:
            if self._refresh_triggered:
                return False
            self._refresh_triggered = True
            return True

    async def refresh_tokens(self, datetime):
        """Call the refresh_tokens function to store updated authentication and director tokens in hass.data."""
        # unused datetime parameter is required, since Home Assistant will pass a datetime.datetime object as parameter when calling this function via async_call_later()
        if await self._get_refreshing_lock():
            await self._refresh_token_with_retry()

    async def _refresh_token_with_retry(self, datetime):
        try:
            await refresh_tokens(self.hass, self.entry)
        except ConfigEntryNotReady:
            self._schedule_refresh_retry()

    def _schedule_refresh_retry(self):
        self.retries += 1
        # exponential backoff with jitter
        delay = random.uniform(0, min(2**self.retries, RETRY_BACKOFF_MAX_SEC))
        _LOGGER.warning("Token refresh failed, trying again in %s seconds", delay)
        entry_data = self.hass.data[DOMAIN][self.entry.entry_id]
        entry_data[CONF_CANCEL_TOKEN_REFRESH_CALLBACK] = async_call_later(
            hass=self.hass,
            delay=delay,
            action=self._refresh_token_with_retry,
        )


class Control4Entity(Entity):
    """Base entity for Control4."""

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
    ) -> None:
        """Initialize a Control4 entity."""
        super().__init__()
        self.entry = entry
        self.entry_data = entry_data
        self._attr_name = name
        self._attr_unique_id = str(idx)
        self._idx = idx
        self._controller_unique_id = entry_data[CONF_CONTROLLER_UNIQUE_ID]
        self._device_name = device_name
        self._device_manufacturer = device_manufacturer
        self._device_model = device_model
        self._device_id = device_id
        self._device_area = device_area
        self._extra_state_attributes = device_attributes
        self._extra_state_attributes["item id"] = idx
        self._extra_state_attributes["parent item id"] = device_id
        # Disable polling
        self._attr_should_poll = False

    async def async_added_to_hass(self):
        """Add entity to hass. Register Websockets callbacks to receive entity state updates from Control4."""
        await super().async_added_to_hass()
        await self.hass.async_add_executor_job(
            self.entry_data[CONF_WEBSOCKET].add_item_callback,
            self._idx,
            self._update_callback,
        )
        _LOGGER.debug("Registering item id %s for callback", self._idx)
        await self.hass.async_add_executor_job(
            self.entry_data[CONF_WEBSOCKET].add_item_callback,
            self._device_id,
            self._update_callback,
        )
        _LOGGER.debug(
            "Registering parent device %s of item id %s for callback",
            self._device_id,
            self._idx,
        )

    async def async_will_remove_from_hass(self) -> None:
        """Entity being removed from hass. Unregister Control4 Websockets callbacks for this entity."""
        try:
            _LOGGER.debug("Deregistering callback for item id %s", self._idx)
            # Pass specific callback for selective removal
            self.entry_data[CONF_WEBSOCKET].remove_item_callback(self._idx, self._update_callback)
            _LOGGER.debug(
                "Deregistering callback for parent device %s of item id %s",
                self._device_id,
                self._idx,
            )
            self.entry_data[CONF_WEBSOCKET].remove_item_callback(self._device_id, self._update_callback)
        except KeyError:
            return

    async def _update_callback(self, device, message):
        """Update state attributes in hass after receiving a Websocket update for our item id/parent device id."""
        _LOGGER.debug(message)

        # Message will be False when a Websocket disconnect is detected
        if message is False:
            self._attr_available = False
        elif message["evtName"] == "OnDataToUI":
            self._attr_available = True
            data = message["data"]
            await self._data_to_extra_state_attributes(data)
        _LOGGER.debug("Message for device %s", device)
        self.async_write_ha_state()

    async def _data_to_extra_state_attributes(self, data) -> None:
        """Load data from Websocket update into extra_state_attributes."""
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict):
                    for k, val in value.items():
                        self._extra_state_attributes[k] = val
                else:
                    self._extra_state_attributes[key.upper()] = value

    @cached_property
    def device_info(self) -> DeviceInfo:
        """Return info of parent Control4 device of entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            manufacturer=self._device_manufacturer,
            model=self._device_model,
            name=self._device_name,
            via_device=(DOMAIN, self._controller_unique_id),
            suggested_area=self._device_area,
        )

    @property
    def extra_state_attributes(self) -> dict:  # type: ignore[override]
        """Return Extra state attributes."""
        return self._extra_state_attributes


class Control4CoordinatorEntity(CoordinatorEntity[Any]):
    """Base entity for Control4."""

    def __init__(
        self,
        entry_data: dict,
        coordinator: DataUpdateCoordinator[Any],
        name: str | None,
        idx: int,
        device_name: str | None,
        device_manufacturer: str | None,
        device_model: str | None,
        device_id: int,
        device_area: str,
        device_attributes: dict,
    ) -> None:
        """Initialize a Control4 entity."""
        super().__init__(coordinator)
        self.entry_data = entry_data
        self._attr_name = name
        self._attr_unique_id = str(idx)
        self._idx = idx
        self._controller_unique_id = entry_data[CONF_CONTROLLER_UNIQUE_ID]
        self._device_name = device_name
        self._device_manufacturer = device_manufacturer
        self._device_model = device_model
        self._device_id = device_id
        self._device_area = device_area
        self._extra_state_attributes = device_attributes
        self._extra_state_attributes["item id"] = idx
        self._extra_state_attributes["parent item id"] = device_id

    @cached_property
    def device_info(self) -> DeviceInfo:
        """Return info of parent Control4 device of entity."""
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._device_id))},
            manufacturer=self._device_manufacturer,
            model=self._device_model,
            name=self._device_name,
            via_device=(DOMAIN, self._controller_unique_id),
            suggested_area=self._device_area,
        )

    @property
    def extra_state_attributes(self) -> dict:  # type: ignore[override]
        """Return Extra state attributes."""
        self._extra_state_attributes.update(self.coordinator.data[self._idx])
        return self._extra_state_attributes

class C4ResettingClientSession(aiohttp.ClientSession):
    """Custom aiohttp ClientSession that can trigger a token refresh and temporarily stop making requests if too many timeouts occur, to avoid spamming the Control4 director with requests when it is unresponsive."""
    def __init__(
        self,
        refresh_tokens_obj: RefreshTokensObject,
        underlying_session: aiohttp.ClientSession,
    ) -> None:
        self._underlying_session = underlying_session
        self._refresh_tokens_obj = refresh_tokens_obj
        self._successive_timeout_count = 0
        self._lock = asyncio.Lock()
        self._connection_is_bad = False

    async def _increment_timeout_count(self, num: int = 1) -> int:
        async with self._lock:
            self._successive_timeout_count += num
            return self._successive_timeout_count

    async def _reset_timeout_count(self):
        async with self._lock:
            self._successive_timeout_count = 0

    async def _request(self, *args, **kwargs) -> aiohttp.ClientResponse:
        if self._connection_is_bad:
            raise CannotConnect("Control4 connection is in bad state, skipping request while token refresh is in progress")

        try:
            result = await self._execute_with_timeout_tracking(self._underlying_session._request(*args, **kwargs))
            # Reset successive timeout count on successful request
            await self._reset_timeout_count()
            return result
        except asyncio.TimeoutError:
            timeout_count = await self._increment_timeout_count()
            # Proactively refresh tokens after 5 successive timeouts
            # These timeouts can occur when Control4 restarts, or when a token is prematurely expired.
            # We only refresh tokens on the exact count since the RefreshTokensObject will keep retrying until it succeeds.
            if timeout_count == 5:
                self._connection_is_bad = True
                _LOGGER.warning(
                    "Too many successive Control4 timeouts (%s). Resetting connection by refreshing tokens.",
                    timeout_count,
                )
                await self._refresh_tokens_obj.refresh_tokens(datetime.now())
            raise
