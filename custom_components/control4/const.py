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

CONF_CONFIG_LISTENER = "config_listener"

CONTROL4_ENTITY_TYPE = 7

# Dynalite gateway listener (TCP only)
CONF_DYNALITE_ENABLED = "dynalite_enabled"
CONF_DYNALITE_HOST = "dynalite_host"
CONF_DYNALITE_PORT = "dynalite_port"
CONF_DYNALITE_PARSE_LAYOUT = "dynalite_parse_layout"
DEFAULT_DYNALITE_PORT = 10001
# Frame layout: "bytes_2_3" = area at byte 2, channel at byte 3; "dynet" = area at byte 1, channel at byte 3 (DyNet standard)
DYNALITE_PARSE_LAYOUT_BYTES_2_3 = "bytes_2_3"
DYNALITE_PARSE_LAYOUT_DYNET = "dynet"
DEFAULT_DYNALITE_PARSE_LAYOUT = DYNALITE_PARSE_LAYOUT_DYNET

RETRY_BACKOFF_MAX_SEC = 30
SCHEDULE_REFRESH_ADVANCE_SEC = 300
