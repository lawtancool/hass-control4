"""Control4 system agents: Variables and Macros."""
from __future__ import annotations

import json
import logging
from typing import Any

from pyControl4.director import C4Director

_LOGGER = logging.getLogger(__name__)

VARIABLES_AGENT_NAME = "variables"
MACROS_AGENT_PROXY = "control4_agent_macros"
MACROS_API_PATH = "/api/v1/agents/macros"
EXECUTE_MACRO_COMMAND = "EXECUTE_MACRO"


def find_variables_agent_id(items: list[dict[str, Any]]) -> int | None:
    """Return the Composer Variables agent item id, if present."""
    for item in items:
        if item.get("typeName") != "agent":
            continue
        if item.get("name") == VARIABLES_AGENT_NAME:
            return item.get("id")
    return None


def find_macros_agent_id(items: list[dict[str, Any]]) -> int | None:
    """Return the Macros agent item id, if present."""
    for item in items:
        if item.get("typeName") != "agent":
            continue
        if item.get("proxy") == MACROS_AGENT_PROXY:
            return item.get("id")
    return None


async def list_macros(director: C4Director) -> list[dict[str, Any]]:
    """Return macros from GET /api/v1/agents/macros."""
    raw = await director.send_get_request(MACROS_API_PATH)
    macros = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(macros, list):
        _LOGGER.warning("Unexpected macros response: %s", macros)
        return []
    return macros


async def execute_macro(
    director: C4Director, macros_agent_id: int, macro_id: int
) -> None:
    """Run a Composer macro via the Macros agent."""
    await director.send_post_request(
        f"/api/v1/items/{macros_agent_id}/commands",
        EXECUTE_MACRO_COMMAND,
        {"id": macro_id},
    )


async def read_custom_variable(
    director: C4Director, variables_agent_id: int, var_name: str
) -> Any:
    """Read one custom variable from the Variables agent."""
    return await director.get_item_variable_value(variables_agent_id, var_name)


async def list_custom_variables(
    director: C4Director, variables_agent_id: int
) -> list[dict[str, Any]]:
    """Return all custom variables defined on the Variables agent."""
    return await director.get_item_variables(variables_agent_id)


def macros_by_name(macros: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index macros by exact Composer name."""
    return {str(m["name"]): m for m in macros if m.get("name") is not None}


def configured_option_names(
    options: dict[str, Any], keys: tuple[str, ...]
) -> list[str]:
    """Collect non-blank option slot values in slot order."""
    names: list[str] = []
    for key in keys:
        raw = options.get(key)
        if raw is None:
            continue
        name = str(raw).strip()
        if name:
            names.append(name)
    return names
