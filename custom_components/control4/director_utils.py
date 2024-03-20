"""Provides data updates from the Control4 controller for platforms."""
import json

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from typing import Any
from collections import defaultdict
from collections.abc import Set

from .const import CONF_DIRECTOR, DOMAIN


async def director_get_entry_variables(
    hass: HomeAssistant, entry: ConfigEntry, item_id: int
) -> dict:
    """Retrieve variable data for Control4 entity."""
    director = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR]
    data = await director.getItemVariables(item_id)

    result = {}
    for item in json.loads(data):
        result[item["varName"]] = item["value"]

    return result

async def update_variables_for_config_entry(
    hass: HomeAssistant, entry: ConfigEntry, variable_names: Set[str]
) -> dict[int, dict[str, Any]]:
    """Retrieve data from the Control4 director."""
    director = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR]
    data = await director.getAllItemVariableValue(variable_names)
    result_dict: defaultdict[int, dict[str, Any]] = defaultdict(dict)
    for item in data:
        result_dict[item["id"]][item["varName"]] = item["value"]
    return dict(result_dict)
