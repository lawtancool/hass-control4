"""Constants for the Control4 integration."""

DOMAIN = "control4"

CONF_ALARM_HOME_MODE = "alarm_home_mode"
DEFAULT_ALARM_HOME_MODE = "(not set)"
CONF_ALARM_AWAY_MODE = "alarm_away_mode"
DEFAULT_ALARM_AWAY_MODE = "(not set)"
CONF_ALARM_NIGHT_MODE = "alarm_night_mode"
DEFAULT_ALARM_NIGHT_MODE = "(not set)"
CONF_ALARM_CUSTOM_BYPASS_MODE = "alarm_custom_bypass_mode"
DEFAULT_ALARM_CUSTOM_BYPASS_MODE = "(not set)"
CONF_ALARM_VACATION_MODE = "alarm_vacation_mode"
DEFAULT_ALARM_VACATION_MODE = "(not set)"

CONF_ACCOUNT = "account"
CONF_DIRECTOR = "director"
CONF_WEBSOCKET = "websocket"
CONF_CANCEL_TOKEN_REFRESH_CALLBACK = "cancel_token_refresh_callback"
CONF_DIRECTOR_SW_VERSION = "director_sw_version"
CONF_DIRECTOR_MODEL = "director_model"
CONF_DIRECTOR_ALL_ITEMS = "director_all_items"
CONF_CONTROLLER_UNIQUE_ID = "controller_unique_id"
CONF_ALARM_ARM_STATES = "alarm_arm_states"
CONF_UI_CONFIGURATION = "ui_configuration"

DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 1

# Comma-delimited Control4 schedule activity names shown as climate preset_modes.
# Director often does not expose PRESETS_LIST; users can override under Configure.
CONF_CLIMATE_SCHEDULE_PRESETS = "climate_schedule_presets"
DEFAULT_CLIMATE_SCHEDULE_PRESETS = (
    "Night",
    "Evening",
    "Day",
    "Home",
    "Away",
    "Off",
)


def default_climate_schedule_presets_csv() -> str:
    """Default schedule presets as a comma-delimited string for the options UI."""
    return ", ".join(DEFAULT_CLIMATE_SCHEDULE_PRESETS)


def parse_climate_schedule_presets(value: str | None) -> list[str]:
    """Parse a comma-delimited presets option; blank falls back to defaults."""
    if value is None or not str(value).strip():
        return list(DEFAULT_CLIMATE_SCHEDULE_PRESETS)
    return [part.strip() for part in str(value).split(",") if part.strip()]


CONF_CONFIG_LISTENER = "config_listener"

CONTROL4_ENTITY_TYPE = 7

RETRY_BACKOFF_MAX_SEC = 30
SCHEDULE_REFRESH_ADVANCE_SEC = 300
