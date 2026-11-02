"""Provides data updates from the Control4 controller for platforms."""
import asyncio
from collections import defaultdict
from collections.abc import Iterable, Set
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_DIRECTOR, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def director_get_entry_variables(
    hass: HomeAssistant, entry: ConfigEntry, item_id: int
) -> dict:
    """Retrieve variable data for Control4 entity."""
    director = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR]
    data = await director.get_item_variables(item_id)

    result = {}
    for item in data:
        result[item["varName"]] = item["value"]

    return result


async def director_get_multiple_entries_variables(
    hass: HomeAssistant,
    entry: ConfigEntry,
    item_ids: Iterable[int],
    max_concurrency: int = 5,
) -> dict[int, dict]:
    """Retrieve variable data for multiple Control4 entities concurrently with bounded concurrency."""
    sem = asyncio.Semaphore(max_concurrency)

    async def _fetch(item_id: int) -> tuple[int, dict]:
        async with sem:
            try:
                return item_id, await director_get_entry_variables(hass, entry, item_id)
            except Exception:
                _LOGGER.warning(
                    "Failed to fetch initial variables for device %s",
                    item_id,
                    exc_info=True,
                )
                return item_id, {}

    results = await asyncio.gather(*[_fetch(item_id) for item_id in item_ids])
    return dict(results)


async def update_variables_for_config_entry(
    hass: HomeAssistant, entry: ConfigEntry, variable_names: Set[str]
) -> dict[int, dict[str, Any]]:
    """Retrieve data from the Control4 director."""
    director = hass.data[DOMAIN][entry.entry_id][CONF_DIRECTOR]
    data = await director.get_all_item_variable_value(variable_names)
    result_dict: defaultdict[int, dict[str, Any]] = defaultdict(dict)
    for item in data:
        result_dict[item["id"]][item["varName"]] = item["value"]
    return dict(result_dict)
