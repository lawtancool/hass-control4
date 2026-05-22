"""The Control4 integration."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from functools import cached_property
from collections.abc import Callable, Coroutine
from logging import config
from typing import Any
import random

import aiohttp
from aiohttp import client_exceptions
from custom_components.control4.config_flow import CannotConnect
from pyControl4.account import C4Account
from pyControl4.director import C4Director
from pyControl4.error_handling import BadCredentials, BadToken, InvalidCategory
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
    CONF_ALARM_ARM_STATES,
    CONF_ALARM_AWAY_MODE,
    CONF_ALARM_CUSTOM_BYPASS_MODE,
    CONF_ALARM_HOME_MODE,
    CONF_ALARM_NIGHT_MODE,
    CONF_ALARM_VACATION_MODE,
    CONF_CONFIG_LISTENER,
    CONF_CONTROLLER_UNIQUE_ID,
    CONF_DIRECTOR,
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_DIRECTOR_MODEL,
    CONF_DIRECTOR_SW_VERSION,
    CONF_C4_SESSION,
    CONF_UI_CONFIGURATION,
    DEFAULT_ALARM_AWAY_MODE,
    DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
    DEFAULT_ALARM_HOME_MODE,
    DEFAULT_ALARM_NIGHT_MODE,
    DEFAULT_ALARM_VACATION_MODE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REFRESH_COOLDOWN_SEC,
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

    entry_data[CONF_C4_SESSION] = C4ClientSession(
        config[CONF_HOST],
        config[CONF_USERNAME],
        config[CONF_PASSWORD],
        config[CONF_CONTROLLER_UNIQUE_ID],
        hass,
        entry,
        lambda director: entry_data.__setitem__(CONF_DIRECTOR, director)
    )
    # Silence C4Websocket related loggers, that would otherwise spam INFO logs with debugging messages
    logging.getLogger("socketio.client").setLevel(logging.WARNING)
    logging.getLogger("engineio.client").setLevel(logging.WARNING)
    logging.getLogger("charset_normalizer").setLevel(logging.ERROR)

    # This starts the connection to Control4 and will automatically reconnect if the connection is lost.
    await entry_data[CONF_C4_SESSION].connect_to_director()

    # Copy controller unique id from config to entry_data for use by entities
    entry_data[CONF_CONTROLLER_UNIQUE_ID] = config[CONF_CONTROLLER_UNIQUE_ID]

    # Add Control4 controller to device registry
    try:
        controller_href = (await entry_data[CONF_C4_SESSION].account.get_account_controllers())[
            "href"
        ]
    except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
        raise ConfigEntryNotReady(exception) from exception

    try:
        entry_data[CONF_DIRECTOR_SW_VERSION] = await entry_data[
            CONF_C4_SESSION
        ].account.get_controller_os_version(controller_href)
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
    # Shuts down the connection to Control4 and stops the re-connection loop.
    await entry_data[CONF_C4_SESSION].teardown()

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
            self.entry_data[CONF_C4_SESSION].add_item_callback,
            self._idx,
            self._update_callback,
        )
        _LOGGER.debug("Registering item id %s for callback", self._idx)
        await self.hass.async_add_executor_job(
            self.entry_data[CONF_C4_SESSION].add_item_callback,
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
            self.entry_data[CONF_C4_SESSION].remove_item_callback(self._idx, self._update_callback)
            _LOGGER.debug(
                "Deregistering callback for parent device %s of item id %s",
                self._device_id,
                self._idx,
            )
            self.entry_data[CONF_C4_SESSION].remove_item_callback(self._device_id, self._update_callback)
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

class C4ClientSession(aiohttp.ClientSession):
    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        controller_unique_id: str,
        hass: HomeAssistant,
        entry: ConfigEntry,
        connect_to_director_callback: Callable[[C4Director], Any] | None = None,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.host = host
        self._controller_unique_id = controller_unique_id

        self.account = C4Account(
            username, password, aiohttp_client.async_get_clientsession(hass)
        )

        self._connect_to_director_callback = connect_to_director_callback

        self.host = entry.data[CONF_HOST]
        aiohttp_client_session = aiohttp_client.async_get_clientsession(hass, verify_ssl=False)
        self._error_detecting_session = ErrorDetectingClientSession(
            aiohttp_client_session,
            self._reset_timeout_count,
            self._try_trigger_token_refresh_for_timeout,
            self._try_trigger_token_refresh,
        )
        self._successive_timeout_count = 0
        self._lock = asyncio.Lock()
        self._connection_is_bad = False
        self._refresh_tokens_object = RefreshObject(hass, self.connect_to_director)
        self._websocket = C4Websocket(
            self.host,
            aiohttp_client_session,
            self._connect_callback,
            self._disconnect_callback,
        )

    def add_item_callback(self, item_id: int, callback: Callable[..., Any]) -> None:
        self._websocket.add_item_callback(item_id, callback)

    def remove_item_callback(self, item_id: int, callback: Callable[..., Any] | None = None) -> None:
        self._websocket.remove_item_callback(item_id, callback)

    async def connect_to_director(self) -> C4Director:
        _LOGGER.info("Attempting to connect to Control4 with credentials")
        director_token_dict = await self._get_director_token_dict()
        director_bearer_token = director_token_dict[CONF_TOKEN]
        token_ttl_sec = director_token_dict["validSeconds"]

        director = C4Director(self.host, director_bearer_token, self._error_detecting_session)

        _LOGGER.debug("Starting new WebSocket connection")
        try:
            await self._websocket.sio_connect(director_bearer_token)
        except Exception as exception:
            raise ConfigEntryNotReady(exception) from exception

        _LOGGER.info("Connected to Control4!")

        # Schedule refresh 5mins before expiry, but no sooner than 5mins from now
        delay = max(
            token_ttl_sec - SCHEDULE_REFRESH_ADVANCE_SEC,
            SCHEDULE_REFRESH_ADVANCE_SEC,
        )
        self._refresh_tokens_object.schedule_refresh(delay)

        await self._connect_callback()
        if self._connect_to_director_callback is not None:
            self._connect_to_director_callback(director)

        return director
    
    async def teardown(self) -> None:
        _LOGGER.debug("Cancelling scheduled token refresh for config entry unload")
        await self._refresh_tokens_object.teardown()
        _LOGGER.debug("Disconnecting C4Websocket for config entry unload")
        await self._websocket.sio_disconnect()

    async def _get_director_token_dict(self) -> dict:
        """Get a director token using the stored account credentials, and trigger token refresh if a BadCredentials or ClientError exception is raised."""
        try:
            await self.account.get_account_bearer_token()
        except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
            raise ConfigEntryNotReady(exception) from exception
        except BadCredentials as exception:
            raise ConfigEntryAuthFailed(exception) from exception

        try:
            director_token_dict = await self.account.get_director_bearer_token(self._controller_unique_id)
        except (client_exceptions.ClientError, asyncio.TimeoutError) as exception:
            raise ConfigEntryNotReady(exception) from exception
        
        return director_token_dict

    async def _connect_callback(self) -> None:
        """Manually refresh entity states when the Websocket is reconnected after a connection drop."""
        async with self._lock:
            if not self._connection_is_bad:
                return

            _LOGGER.info("Websocket connection to Control4 reestablished")
            await self._mark_entities_as_available()
            self._connection_is_bad = False
            self._error_detecting_session.connection_is_bad = False

    async def _disconnect_callback(self) -> None:
        """Detect a Websocket connection loss."""
        _LOGGER.warning(
            "Websocket connection to Control4 lost, attempting reconnection"
        )
        await self._try_trigger_token_refresh(is_timeout=False)

    async def _reset_timeout_count(self) -> None:
        async with self._lock:
            self._successive_timeout_count = 0

    async def _try_trigger_token_refresh_for_timeout(self) -> None:
        await self._try_trigger_token_refresh(is_timeout=True)

    async def _try_trigger_token_refresh(self, is_timeout=False) -> None:
        async with self._lock:
            if is_timeout:
                self._successive_timeout_count += 1

            if self._connection_is_bad or (is_timeout and self._successive_timeout_count < 5):
                return
            else:
                _LOGGER.warning("Triggering token refresh due to detected bad Control4 connection")
                self._connection_is_bad = True
                self._error_detecting_session.connection_is_bad = True
                await self._mark_entities_as_unavailable()

        # This call needs to be made outside the lock to avoid recursive locking
        await self._refresh_tokens_object.refresh(datetime.now())

    async def _mark_entities_as_available(self) -> None:
        # Refresh state of entities so they are not unavailable anymore
        item_callbacks = self._websocket.item_callbacks
        for item_id, callback_list in item_callbacks.items():
            item_attributes = await director_get_entry_variables(
                self.hass, self.entry, item_id
            )
            message = {
                "evtName": "OnDataToUI",
                "iddevice": item_id,
                "data": item_attributes,
            }
            for callback in callback_list:
                await callback(item_id, message)

    async def _mark_entities_as_unavailable(self) -> None:
        # Set all entities to unavailable
        item_callbacks = self._websocket.item_callbacks
        for item_id, callback_list in item_callbacks.items():
            for callback in callback_list:
                await callback(item_id, False)


class ErrorDetectingClientSession(aiohttp.ClientSession):
    def __init__(
        self,
        underlying_session: aiohttp.ClientSession,
        reset_timeout_count_callback: Callable[[], Coroutine[Any, Any, None]],
        timeout_error_callback: Callable[[], Coroutine[Any, Any, None]],
        bad_token_error_callback: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self._underlying_session = underlying_session
        self._reset_timeout_count_callback = reset_timeout_count_callback
        self._timeout_error_callback = timeout_error_callback
        self._bad_token_error_callback = bad_token_error_callback
        self.connection_is_bad = False
    
    async def _request(self, *args, **kwargs) -> aiohttp.ClientResponse:
        """Override of aiohttp ClientSession _request method to trigger token refresh on BadToken exceptions and to stop making requests when the connection is in a bad state due to multiple timeouts."""
        if self.connection_is_bad:
            raise CannotConnect("Control4 connection is in bad state, skipping request while token refresh is in progress")

        try:
            result = await self._underlying_session._request(*args, **kwargs)
            # Reset successive timeout count on successful request
            # Use create_task to avoid locking requests across all entities
            asyncio.create_task(self._reset_timeout_count_callback())
            return result
        except BadToken:
            asyncio.create_task(self._bad_token_error_callback())
            raise
        except asyncio.TimeoutError:
            # Proactively refresh tokens after 5 successive timeouts
            # These timeouts can occur when Control4 restarts, or when a token is prematurely expired.
            asyncio.create_task(self._timeout_error_callback())
            raise


class RefreshObject:
    """Object that can trigger a refresh with incremental backoff."""

    def __init__(
        self,
        hass: HomeAssistant,
        refresh_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        self.hass = hass
        self._refresh_fn = refresh_fn
        self.retries = 0
        self._refresh_lock = asyncio.Lock()
        self._teardown_triggered = False
        self._next_allowable_refresh_time = datetime.now()
        self._scheduled_refresh_delayed_task = None

    async def teardown(self) -> None:
        """Teardown function to be called on config entry unload to cancel any pending refreshes and prevent memory leaks from multiple simultaneous refreshes."""
        async with self._refresh_lock:
            self._teardown_triggered = True
            self._cancel_scheduled_refresh()

    def schedule_refresh(self, delay: int) -> None:
        """Schedule a refresh by calling Home Assistant's async_call_later with the refresh function as callback."""
        _LOGGER.debug("Registering next refresh in %s seconds", delay)

        self._cancel_scheduled_refresh()

        self._scheduled_refresh_delayed_task = async_call_later(
            hass=self.hass,
            delay=delay,
            action=self.refresh,
        )

    async def refresh(self, datetime) -> None:
        """Trigger a refresh by calling the provided refresh function. This function is designed to be called by Home Assistant's async_call_later, which is why it accepts a datetime parameter that is not used."""
        # unused datetime parameter is required, since Home Assistant will pass a datetime.datetime object as parameter when calling this function via async_call_later()
        async with self._refresh_lock:
            if self._teardown_triggered:
                _LOGGER.warning("C4 config entry is unloading, skipping token refresh")
                return
            if self._next_allowable_refresh_time > datetime.now():
                # Limit the frequency of token refreshes to avoid spamming the Control4 director with refresh requests in a short period of time.
                _LOGGER.warning("C4 token refresh rate limited. Next allowable refresh time: %s", self._next_allowable_refresh_time)
                return

            try:
                await self._refresh_fn()
                self.retries = 0 # Reset retry count on successful refresh
                # On successful refresh, delay the next allowable refresh time to avoid multiple simultaneous refresh attempts.
                self._next_allowable_refresh_time = datetime.now() + timedelta(seconds=REFRESH_COOLDOWN_SEC)
            except ConfigEntryNotReady:
                self._schedule_refresh_retry()

    def _cancel_scheduled_refresh(self) -> None:
        if self._scheduled_refresh_delayed_task is not None:
            self._scheduled_refresh_delayed_task()
            self._scheduled_refresh_delayed_task = None

    def _schedule_refresh_retry(self) -> None:
        self.retries += 1
        # exponential backoff with jitter
        delay = random.uniform(0, min(2**self.retries, RETRY_BACKOFF_MAX_SEC))
        _LOGGER.warning("Token refresh failed, trying again in %s seconds", delay)
        self.schedule_refresh(delay)
        self._next_allowable_refresh_time = datetime.now() + timedelta(seconds=delay)
