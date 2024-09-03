"""Config flow for Control4 integration."""
from asyncio import TimeoutError as asyncioTimeoutError
import logging

from aiohttp.client_exceptions import ClientError
from pyControl4.account import C4Account
from pyControl4.director import C4Director
from pyControl4.error_handling import NotFound, Unauthorized
import voluptuous as vol

from homeassistant import config_entries, exceptions
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.helpers.device_registry import format_mac

from .const import (
    CONF_ALARM_ARM_STATES,
    CONF_ALARM_AWAY_MODE,
    CONF_ALARM_CUSTOM_BYPASS_MODE,
    CONF_ALARM_HOME_MODE,
    CONF_ALARM_NIGHT_MODE,
    CONF_ALARM_VACATION_MODE,
    CONF_CONTROLLER_UNIQUE_ID,
    DEFAULT_ALARM_AWAY_MODE,
    DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
    DEFAULT_ALARM_HOME_MODE,
    DEFAULT_ALARM_NIGHT_MODE,
    DEFAULT_ALARM_VACATION_MODE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class Control4Validator:
    """Validates that config details can be used to authenticate and communicate with Control4."""

    def __init__(self, host, username, password, hass):
        """Initialize."""
        self.host = host
        self.username = username
        self.password = password
        self.controller_unique_id = None
        self.director_bearer_token = None
        self.hass = hass

    async def authenticate(self) -> bool:
        """Test if we can authenticate with the Control4 account API."""
        try:
            account_session = aiohttp_client.async_get_clientsession(self.hass)
            account = C4Account(self.username, self.password, account_session)
            # Authenticate with Control4 account
            await account.getAccountBearerToken()

            # Get controller name
            account_controllers = await account.getAccountControllers()
            self.controller_unique_id = account_controllers["controllerCommonName"]

            # Get bearer token to communicate with controller locally
            self.director_bearer_token = (
                await account.getDirectorBearerToken(self.controller_unique_id)
            )["token"]
            return True
        except (Unauthorized, NotFound):
            return False

    async def connect_to_director(self) -> bool:
        """Test if we can connect to the local Control4 Director."""
        try:
            director_session = aiohttp_client.async_get_clientsession(
                self.hass, verify_ssl=False
            )
            director = C4Director(
                self.host, self.director_bearer_token, director_session
            )
            await director.getAllItemInfo()
            return True
        except (Unauthorized, ClientError, asyncioTimeoutError):
            _LOGGER.error("Failed to connect to the Control4 controller")
            return False


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Control4."""

    VERSION = 1

    async def _validate_input(self, user_input):
        errors = {}
        hub = Control4Validator(
            user_input[CONF_HOST],
            user_input[CONF_USERNAME],
            user_input[CONF_PASSWORD],
            self.hass,
        )
        try:
            if not await hub.authenticate():
                raise InvalidAuth
            if not await hub.connect_to_director():
                raise CannotConnect
        except InvalidAuth:
            errors["base"] = "invalid_auth"
        except CannotConnect:
            errors["base"] = "cannot_connect"
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected exception")
            errors["base"] = "unknown"

        return errors, hub.controller_unique_id

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            errors, controller_unique_id = await self._validate_input(user_input)
            if not errors:
                mac = (controller_unique_id.split("_", 3))[2]
                formatted_mac = format_mac(mac)
                data = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_CONTROLLER_UNIQUE_ID: controller_unique_id,
                }
                await self.async_set_unique_id(formatted_mac)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=controller_unique_id,
                    data=data,
                )

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_user_reauth(self, user_input=None):
        """Handle a reauthentication request."""
        errors = {}
        if user_input is not None:
            errors, controller_unique_id = await self._validate_input(user_input)
            if not errors:
                mac = (controller_unique_id.split("_", 3))[2]
                formatted_mac = format_mac(mac)
                data = {
                    CONF_HOST: user_input[CONF_HOST],
                    CONF_USERNAME: user_input[CONF_USERNAME],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                    CONF_CONTROLLER_UNIQUE_ID: controller_unique_id,
                }
                _LOGGER.debug("Reauthentication occurring")
                existing_entry = await self.async_set_unique_id(formatted_mac)
                self.hass.config_entries.async_update_entry(existing_entry, data=data)
                await self.hass.config_entries.async_reload(existing_entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="user_reauth", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_reauth(self, user_input=None):
        """Perform reauth upon an API authentication error."""
        return await self.async_step_user_reauth()

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle a option flow for Control4."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        if user_input is not None:
            _LOGGER.debug(user_input)
            return self.async_create_entry(title="", data=user_input)

        # TODO: figure out how to accept empty strings to disable modes
        # TODO: figure out how to only show alarm options if a alarm_control_panel entity exists
        self.entry_data = self.hass.data[DOMAIN][self.config_entry.entry_id]
        _LOGGER.debug(self.entry_data[CONF_ALARM_ARM_STATES])
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                    ),
                ): vol.All(cv.positive_int, vol.Clamp(min=MIN_SCAN_INTERVAL)),
                vol.Optional(
                    CONF_ALARM_AWAY_MODE,
                    default=self.config_entry.options.get(
                        CONF_ALARM_AWAY_MODE, DEFAULT_ALARM_AWAY_MODE
                    ),
                ): vol.In(self.entry_data[CONF_ALARM_ARM_STATES]),
                vol.Optional(
                    CONF_ALARM_HOME_MODE,
                    default=self.config_entry.options.get(
                        CONF_ALARM_HOME_MODE, DEFAULT_ALARM_HOME_MODE
                    ),
                ): vol.In(self.entry_data[CONF_ALARM_ARM_STATES]),
                vol.Optional(
                    CONF_ALARM_NIGHT_MODE,
                    default=self.config_entry.options.get(
                        CONF_ALARM_NIGHT_MODE, DEFAULT_ALARM_NIGHT_MODE
                    ),
                ): vol.In(self.entry_data[CONF_ALARM_ARM_STATES]),
                vol.Optional(
                    CONF_ALARM_CUSTOM_BYPASS_MODE,
                    default=self.config_entry.options.get(
                        CONF_ALARM_CUSTOM_BYPASS_MODE, DEFAULT_ALARM_CUSTOM_BYPASS_MODE
                    ),
                ): vol.In(self.entry_data[CONF_ALARM_ARM_STATES]),
                vol.Optional(
                    CONF_ALARM_VACATION_MODE,
                    default=self.config_entry.options.get(
                        CONF_ALARM_VACATION_MODE, DEFAULT_ALARM_VACATION_MODE
                    ),
                ): vol.In(self.entry_data[CONF_ALARM_ARM_STATES]),
            },
            required=False,
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
