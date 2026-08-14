"""Shared helpers for Control4 alarm control panel."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ALARM_ARM_STATES,
    CONF_ALARM_AWAY_MODE,
    CONF_ALARM_CUSTOM_BYPASS_MODE,
    CONF_ALARM_HOME_MODE,
    CONF_ALARM_NIGHT_MODE,
    CONF_ALARM_VACATION_MODE,
    DEFAULT_ALARM_AWAY_MODE,
    DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
    DEFAULT_ALARM_HOME_MODE,
    DEFAULT_ALARM_NIGHT_MODE,
    DEFAULT_ALARM_VACATION_MODE,
)

CONTROL4_PARTITION_STATE_VAR = "PARTITION_STATE"


def parse_arm_types_from_capabilities(capabilities: dict | None) -> list[str]:
    """Return arm type names from Director item capabilities."""
    if not capabilities:
        return []
    types: list[str] = []
    for key in ("arm_types", "arm_states"):
        raw = capabilities.get(key, "")
        if raw:
            types.extend(t.strip() for t in str(raw).split(",") if t.strip())
    # Preserve order, dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for name in types:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def merge_arm_types_into_cache(cache: set[str], arm_types: list[str]) -> None:
    """Add discovered arm types to the integration arm-state choice cache."""
    for arm_type in arm_types:
        if arm_type:
            cache.add(arm_type)


def _match_arm_type(arm_types: list[str], candidates: tuple[str, ...]) -> str | None:
    """Return the first arm type matching any candidate (case-insensitive)."""
    lowered = {t.lower(): t for t in arm_types}
    for candidate in candidates:
        match = lowered.get(candidate.lower())
        if match:
            return match
    return None


def auto_map_ha_modes(arm_types: list[str]) -> dict[str, str]:
    """Map Control4 arm type names to HA alarm mode option keys."""
    if not arm_types:
        return {}

    mapping: dict[str, str] = {}
    away = _match_arm_type(arm_types, ("Away",))
    if away:
        mapping[CONF_ALARM_AWAY_MODE] = away

    home = _match_arm_type(arm_types, ("Stay", "Home"))
    if home:
        mapping[CONF_ALARM_HOME_MODE] = home

    night = _match_arm_type(arm_types, ("Night",))
    if night:
        mapping[CONF_ALARM_NIGHT_MODE] = night

    vacation = _match_arm_type(arm_types, ("Vacation",))
    if vacation:
        mapping[CONF_ALARM_VACATION_MODE] = vacation

    custom = _match_arm_type(arm_types, ("Bypass", "Custom"))
    if custom:
        mapping[CONF_ALARM_CUSTOM_BYPASS_MODE] = custom

    return mapping


def apply_auto_mapped_modes(
    entry_options: dict,
    entry_data: dict,
    arm_types: list[str],
) -> dict | None:
    """Apply auto-mapped modes when user options are still default. Returns new options if changed."""
    auto_mapped = auto_map_ha_modes(arm_types)
    if not auto_mapped:
        return None

    defaults = {
        CONF_ALARM_AWAY_MODE: DEFAULT_ALARM_AWAY_MODE,
        CONF_ALARM_HOME_MODE: DEFAULT_ALARM_HOME_MODE,
        CONF_ALARM_NIGHT_MODE: DEFAULT_ALARM_NIGHT_MODE,
        CONF_ALARM_CUSTOM_BYPASS_MODE: DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
        CONF_ALARM_VACATION_MODE: DEFAULT_ALARM_VACATION_MODE,
    }

    new_options = dict(entry_options)
    changed = False
    for option_key, default_value in defaults.items():
        current = entry_options.get(option_key, default_value)
        if current != default_value:
            continue
        mapped = auto_mapped.get(option_key)
        if mapped and mapped != default_value:
            new_options[option_key] = mapped
            entry_data[option_key] = mapped
            changed = True

    return new_options if changed else None


def is_usable_partition(item_attributes: dict, arm_types: list[str]) -> bool:
    """Return True if this security item is a usable alarm partition."""
    if arm_types:
        return True
    return CONTROL4_PARTITION_STATE_VAR in item_attributes


def arm_state_choices(entry_data: dict) -> list[str]:
    """Return sorted arm state choices including (not set)."""
    choices = set(entry_data.get(CONF_ALARM_ARM_STATES, set()))
    choices.update(
        {
            DEFAULT_ALARM_AWAY_MODE,
            DEFAULT_ALARM_HOME_MODE,
            DEFAULT_ALARM_NIGHT_MODE,
            DEFAULT_ALARM_CUSTOM_BYPASS_MODE,
            DEFAULT_ALARM_VACATION_MODE,
        }
    )
    return sorted(choices)


async def async_discover_alarm_arm_types(
    hass: HomeAssistant, entry: ConfigEntry, entry_data: dict
) -> list[str]:
    """Discover arm types from security items and populate CONF_ALARM_ARM_STATES."""
    from pyControl4.alarm import C4SecurityPanel

    from . import get_items_of_category
    from .const import CONF_DIRECTOR, CONTROL4_ENTITY_TYPE

    director = entry_data[CONF_DIRECTOR]
    all_arm_types: list[str] = []

    try:
        items = await get_items_of_category(hass, entry, "security")
    except Exception:  # noqa: BLE001
        return all_arm_types

    for item in items:
        if item.get("type") != CONTROL4_ENTITY_TYPE or not item.get("id"):
            continue
        cap_types = parse_arm_types_from_capabilities(item.get("capabilities"))
        merge_arm_types_into_cache(entry_data[CONF_ALARM_ARM_STATES], cap_types)
        c4_alarm = C4SecurityPanel(director, item["id"])
        try:
            item_arm_types = await c4_alarm.get_arm_types()
        except Exception:  # noqa: BLE001
            item_arm_types = []
        if not item_arm_types:
            item_arm_types = cap_types
        merge_arm_types_into_cache(entry_data[CONF_ALARM_ARM_STATES], item_arm_types)
        all_arm_types.extend(item_arm_types)

    return list(dict.fromkeys(all_arm_types))
