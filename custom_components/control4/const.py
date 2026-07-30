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
CONF_POOL_DEVICES = "pool_devices"

# Pool / spa aux circuit slots 1–5: optional friendly name per Control4 aux ID.
# Blank name = that circuit is not exposed as a switch.
POOL_AUX_SLOT_COUNT = 5
CONF_POOL_AUX_NAME_KEYS = tuple(
    f"pool_aux_{i}_name" for i in range(1, POOL_AUX_SLOT_COUNT + 1)
)

# Legacy option keys (pre-1.8.1 role-based mapping); migrated at runtime / on save
CONF_POOL_LIGHT_AUX_ID = "pool_light_aux_id"
CONF_SPA_LIGHT_AUX_ID = "spa_light_aux_id"
CONF_SPA_BLOWER_AUX_ID = "spa_blower_aux_id"
LEGACY_POOL_AUX_OPTION_KEYS = (
    CONF_POOL_LIGHT_AUX_ID,
    CONF_SPA_LIGHT_AUX_ID,
    CONF_SPA_BLOWER_AUX_ID,
)

DEFAULT_SCAN_INTERVAL = 5
MIN_SCAN_INTERVAL = 1

CONF_CONFIG_LISTENER = "config_listener"

CONTROL4_ENTITY_TYPE = 7

RETRY_BACKOFF_MAX_SEC = 30
SCHEDULE_REFRESH_ADVANCE_SEC = 300
