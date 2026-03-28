"""Helpers to map C4 room/floor to HA Area/Floor and build a combined report table.

WHAT: Maps Control4 (C4) room/floor from the director to Home Assistant (HA) areas
and floors. Supports building a report table (show in notification) and applying
C4 locations to HA (create areas/floors, assign devices).

WHY: C4 devices live in rooms/floors; HA uses areas and (optionally) floors. This
lets users see the mapping and one-shot sync C4 locations into HA so devices
appear in the right area/floor in the UI.

HOW: Uses director_all_items (C4 project data) for roomName/floorName with a
parent-walk when an item has none. Uses HA entity/device/area/floor registries for
current HA state. Apply creates missing floors/areas by name and assigns devices.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import CONF_DIRECTOR_ALL_ITEMS, DOMAIN

try:
    from homeassistant.helpers import floor_registry as fr
except ImportError:
    fr = None  # Floor registry added in HA 2024.3; older HA has no floors

# Area/floor mapping and floor-aware apply require the floor registry (HA 2024.3+).
LOCATION_FLOOR_FEATURES_AVAILABLE: bool = fr is not None

_LOGGER = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# C4 location lookup (director data)
# -----------------------------------------------------------------------------


def get_c4_room_floor_from_map(
    items_by_id: dict[int, dict], item_id: int
) -> tuple[str, str]:
    """Return (roomName, floorName) for a C4 item id using a prebuilt id→item map.

    Rationale: In C4, only some items (e.g. room, device) have roomName/floorName;
    child items may not. We walk parentId until we find an item that has location
    so every entity gets a consistent room/floor from its hierarchy.
    """
    current_id: int | None = item_id
    while current_id is not None:
        item = items_by_id.get(current_id)
        if not item:
            return ("", "")
        room_name = item.get("roomName") or ""
        floor_name = item.get("floorName") or ""
        if room_name or floor_name:
            return (room_name, floor_name)
        current_id = item.get("parentId")
    return ("", "")


def get_c4_room_floor(director_all_items: list[dict], item_id: int) -> tuple[str, str]:
    """Same as get_c4_room_floor_from_map but builds the map (O(items)); prefer the _from_map API in hot loops."""
    items_by_id = {item["id"]: item for item in director_all_items if item.get("id")}
    return get_c4_room_floor_from_map(items_by_id, item_id)


def get_ha_area_floor_for_device(
    hass: HomeAssistant, device: dr.DeviceEntry | None
) -> tuple[str, str]:
    """Return (area_name, floor_name) for a device registry entry. Returns ("", "") when not set."""
    if not device or not device.area_id:
        return ("", "")

    area_reg = ar.async_get(hass)
    area = area_reg.async_get_area(device.area_id)
    if not area:
        return ("", "")

    area_name = area.name or ""
    floor_name = ""
    if fr and area.floor_id:
        floor_reg = fr.async_get(hass)
        floor = floor_reg.async_get_floor(area.floor_id)
        if floor:
            floor_name = floor.name or ""

    return (area_name, floor_name)


def get_ha_area_floor(hass: HomeAssistant, device_id: str) -> tuple[str, str]:
    """Return (area_name, floor_name) for a HA device id using registries.

    Device is looked up by (DOMAIN, device_id). Returns ("", "") when not set.
    """
    dev_reg = dr.async_get(hass)
    device = dev_reg.async_get_device(identifiers={(DOMAIN, device_id)})
    return get_ha_area_floor_for_device(hass, device)


# -----------------------------------------------------------------------------
# Table formatting (log + notification)
# -----------------------------------------------------------------------------

TABLE_HEADERS = ["id", "entity_id", "name", "ha_area", "ha_floor", "c4_room", "c4_floor"]


def _format_table(rows: list[dict[str, Any]], max_rows: int = 100) -> str:
    """Format rows as a fixed-width table for logging. Why: readable in logs."""
    if not rows:
        return "(no entities)"

    col_widths = {
        "id": 6,
        "entity_id": 28,
        "name": 22,
        "ha_area": 14,
        "ha_floor": 14,
        "c4_room": 14,
        "c4_floor": 14,
    }
    lines = []
    header_line = "  ".join(h.ljust(col_widths[h]) for h in TABLE_HEADERS)
    lines.append(header_line)
    lines.append("-" * len(header_line))

    for i, row in enumerate(rows):
        if i >= max_rows:
            lines.append(f"... and {len(rows) - max_rows} more entities")
            break
        parts = []
        for key in TABLE_HEADERS:
            val = str((row.get(key) or ""))[: col_widths[key]]
            parts.append(val.ljust(col_widths[key]))
        lines.append("  ".join(parts))

    return "\n".join(lines)


def format_table_markdown(rows: list[dict[str, Any]], max_rows: int = 150) -> str:
    """Format rows as markdown for persistent_notification. Why: HA renders markdown as a table."""
    if not rows:
        return "_No entities_"

    def escape_cell(val: Any) -> str:
        s = str(val or "").replace("|", "\\|").replace("\n", " ")
        return s[:50] if len(s) > 50 else s

    header_row = "| " + " | ".join(TABLE_HEADERS) + " |"
    separator = "|" + "|".join("---" for _ in TABLE_HEADERS) + "|"

    lines = [header_row, separator]
    for i, row in enumerate(rows):
        if i >= max_rows:
            lines.append(f"| _… and {len(rows) - max_rows} more_ |" + " |" * (len(TABLE_HEADERS) - 1))
            break
        cells = [escape_cell(row.get(h)) for h in TABLE_HEADERS]
        lines.append("| " + " | ".join(cells) + " |")

    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Build combined table (HA entities + C4 and HA location)
# -----------------------------------------------------------------------------


async def async_build_location_floor_table(
    hass: HomeAssistant, entry: ConfigEntry
) -> list[dict[str, Any]]:
    """Build a combined table of C4 entities with HA and C4 area/floor.

    Only includes rows for HA entities that belong to this config entry (entity
    registry). Items without an HA entity (e.g. unsupported device types, or
    entities skipped due to non-integer unique_id / no device_id / device not
    in registry) do not appear. Returns a list of dicts: id, name, ha_area,
    ha_floor, c4_room, c4_floor (and optionally device_id for later use).
    Sorted by id.
    """
    # Why: table is entity-centric so "Show table" and "Apply" only deal with
    # devices that actually have HA entities.
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not entry_data:
        _LOGGER.debug("No entry data for config entry %s", entry.entry_id)
        return []

    director_all_items = entry_data.get(CONF_DIRECTOR_ALL_ITEMS)
    if not director_all_items:
        _LOGGER.warning("No director_all_items for config entry %s", entry.entry_id)
        return []

    entity_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)

    items_by_id = {
        item["id"]: item for item in director_all_items if item.get("id")
    }

    rows: list[dict[str, Any]] = []
    for entity in entity_reg.entities.values():
        if entity.config_entry_id != entry.entry_id:
            continue

        try:
            item_id = int(entity.unique_id)
        except (ValueError, TypeError):
            continue

        device_id = entity.device_id
        if not device_id:
            continue

        device = dev_reg.async_get(device_id)
        if not device:
            continue

        # HA device_id is registry-internal; C4 uses (DOMAIN, parent_item_id). Get it from identifiers.
        c4_device_id = ""
        for ident in device.identifiers:
            if ident[0] == DOMAIN:
                c4_device_id = str(ident[1])
                break

        ha_area, ha_floor = get_ha_area_floor_for_device(hass, device)
        c4_room, c4_floor = get_c4_room_floor_from_map(items_by_id, item_id)

        name = entity.original_name or entity.name or device.name_by_user or device.name or ""
        entity_id = entity.entity_id or ""

        rows.append(
            {
                "id": item_id,
                "entity_id": entity_id,
                "name": name,
                "ha_area": ha_area,
                "ha_floor": ha_floor,
                "c4_room": c4_room,
                "c4_floor": c4_floor,
                "device_id": device.id,
                "c4_device_id": c4_device_id,
            }
        )

    rows.sort(key=lambda r: r["id"])
    return rows


# -----------------------------------------------------------------------------
# Apply: create HA areas/floors from C4 and assign devices
# -----------------------------------------------------------------------------

def _normalize(s: str) -> str:
    """Stripped string; empty for None/whitespace. Why: consistent (floor, room) keys and comparisons."""
    return (s or "").strip()


def _get_floor_id_by_name(hass: HomeAssistant, name: str):
    """Return floor_id for the given floor name, or None if not found / fr unavailable."""
    if not name or not fr:
        return None
    floor_reg = fr.async_get(hass)
    for floor in floor_reg.async_list_floors():
        if (floor.name or "").strip() == name:
            return floor.floor_id
    return None


def _get_area_id_by_name_and_floor(
    hass: HomeAssistant, area_name: str, floor_id: str | None
) -> str | None:
    """Area by name + floor_id. Why: same name on different floors (e.g. Living Room) are different areas."""
    area_reg = ar.async_get(hass)
    for area in area_reg.async_list_areas():
        if (area.name or "").strip() != area_name:
            continue
        if (area.floor_id or None) == floor_id:
            return area.id
    return None


def _get_area_id_by_name(hass: HomeAssistant, area_name: str) -> str | None:
    """First area with given name (any floor). Used when create fails with 'already in use' (area exists without floor)."""
    area_reg = ar.async_get(hass)
    for area in area_reg.async_list_areas():
        if (area.name or "").strip() == area_name:
            return area.id
    return None


async def async_apply_area_floor_to_ha(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Create missing HA areas/floors from C4 and assign devices.

    What: For each (c4_floor, c4_room) that doesn't match HA yet, ensure floor/area
    exist (by name), then set each device's area_id. Reuses the same table as "Show".
    Why: One-shot sync so C4 layout is reflected in HA without manual area assignment.
    Returns: created_floors, created_areas, updated_devices, errors, skipped_no_area,
    mismatched_after_apply.
    """
    summary: dict[str, Any] = {
        "created_floors": [],
        "created_areas": [],
        "updated_devices": 0,
        "errors": [],
        "skipped_no_area": [],  # list of (row_id, c4_floor, c4_room) when area_id missing
        "skipped_no_c4_room": [],  # C4 has no room name; cannot create/sync HA area from C4
    }
    rows = await async_build_location_floor_table(hass, entry)
    if not rows:
        return summary

    area_reg = ar.async_get(hass)
    dev_reg = dr.async_get(hass)
    floor_reg = fr.async_get(hass) if fr else None

    # Collect (floor, room) pairs that need an area; skip already-matching or empty C4 location
    need_locations: set[tuple[str, str]] = set()
    for row in rows:
        c4_room = _normalize(row.get("c4_room") or "")
        c4_floor = _normalize(row.get("c4_floor") or "")
        ha_area = _normalize(row.get("ha_area") or "")
        ha_floor = _normalize(row.get("ha_floor") or "")
        if not c4_room and not c4_floor:
            continue
        if not c4_room:
            if ha_area:
                continue
            summary["skipped_no_c4_room"].append(row.get("id"))
            continue
        if ha_area == c4_room and ha_floor == c4_floor:
            continue
        need_locations.add((c4_floor, c4_room))

    # Build or find floor and area for each (c4_floor, c4_room); cache for device assignment
    location_to_area_id: dict[tuple[str, str], str] = {}

    for c4_floor, c4_room in need_locations:
        floor_id = None
        if c4_floor and floor_reg:
            floor_id = _get_floor_id_by_name(hass, c4_floor)
            if floor_id is None:
                try:
                    new_floor = floor_reg.async_create(c4_floor)
                    floor_id = new_floor.floor_id
                    summary["created_floors"].append(c4_floor)
                except Exception as e:  # pylint: disable=broad-except
                    summary["errors"].append(f"Create floor '{c4_floor}': {e}")
                    continue

        area_id = _get_area_id_by_name_and_floor(hass, c4_room, floor_id)
        if area_id is None:
            try:
                new_area = area_reg.async_create(c4_room)
                area_id = new_area.id
                summary["created_areas"].append(c4_room)
                if floor_id:
                    area_reg.async_update(area_id, floor_id=floor_id)
            except Exception as e:  # pylint: disable=broad-except
                err_msg = str(e)
                # Rationale: Area may already exist without floor (e.g. created manually). Use it and link floor.
                if "already in use" in err_msg.lower():
                    area_id = _get_area_id_by_name(hass, c4_room)
                    if area_id and floor_id:
                        try:
                            area_reg.async_update(area_id, floor_id=floor_id)
                        except Exception:  # pylint: disable=broad-except
                            pass
                if area_id is None:
                    summary["errors"].append(f"Create area '{c4_room}': {e}")
                    continue
        location_to_area_id[(c4_floor, c4_room)] = area_id

    # Assign each device to the area for its (c4_floor, c4_room)
    for row in rows:
        c4_room = _normalize(row.get("c4_room") or "")
        c4_floor = _normalize(row.get("c4_floor") or "")
        if not c4_room and not c4_floor:
            continue
        if not c4_room:
            continue
        ha_area = _normalize(row.get("ha_area") or "")
        ha_floor = _normalize(row.get("ha_floor") or "")
        if ha_area == c4_room and ha_floor == c4_floor:
            continue
        area_id = location_to_area_id.get((c4_floor, c4_room))
        if not area_id:
            summary["skipped_no_area"].append(
                (row.get("id"), c4_floor, c4_room)
            )
            continue
        device_id = row.get("device_id")
        if not device_id:
            continue
        try:
            dev_reg.async_update_device(device_id, area_id=area_id)
            summary["updated_devices"] += 1
        except Exception as e:  # pylint: disable=broad-except
            summary["errors"].append(f"Update device {device_id}: {e}")

    # Post-apply: how many entities still have HA != C4 (e.g. skipped or errors)
    rows_after = await async_build_location_floor_table(hass, entry)
    mismatched = 0
    for row in rows_after:
        c4_room = _normalize(row.get("c4_room") or "")
        c4_floor = _normalize(row.get("c4_floor") or "")
        if not c4_room and not c4_floor:
            continue
        if not c4_room:
            continue
        ha_area = _normalize(row.get("ha_area") or "")
        ha_floor = _normalize(row.get("ha_floor") or "")
        if ha_area != c4_room or ha_floor != c4_floor:
            mismatched += 1
    summary["mismatched_after_apply"] = mismatched

    return summary


async def async_report_area_floor_mapping(
    hass: HomeAssistant, config_entry_id: str | None = None
) -> list[dict[str, Any]]:
    """Build the table, log at INFO, return rows (no device_id in output). For services/callers that need the table only."""
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        _LOGGER.warning("No Control4 config entries found")
        return []

    entry = None
    if config_entry_id:
        for e in entries:
            if e.entry_id == config_entry_id:
                entry = e
                break
    if not entry:
        entry = entries[0]

    rows = await async_build_location_floor_table(hass, entry)
    table = _format_table(rows)
    _LOGGER.info(
        "Control4 area/floor mapping (entry_id=%s):\n%s",
        entry.entry_id,
        table,
    )
    # Return without internal device_id keys for service response
    return [
        {k: v for k, v in row.items() if k not in ("device_id", "c4_device_id")}
        for row in rows
    ]
