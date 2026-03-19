"""Dynalite gateway event listener (TCP) for Control4 Dynalite trigger binary sensors."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_DIRECTOR_ALL_ITEMS,
    CONF_DYNALITE_ENABLED,
    CONF_DYNALITE_HOST,
    CONF_DYNALITE_PARSE_LAYOUT,
    CONF_DYNALITE_PORT,
    DEFAULT_DYNALITE_PARSE_LAYOUT,
    DEFAULT_DYNALITE_PORT,
    DOMAIN,
    DYNALITE_PARSE_LAYOUT_DYNET,
)
from .director_utils import director_get_item_properties

_LOGGER = logging.getLogger(__name__)


async def build_dynalite_event_map(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[tuple[int, int], int]:
    """Build (area, channel) -> C4 item_id from Director dynalite_trigger items and their properties."""
    result: dict[tuple[int, int], int] = {}
    entry_data = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)
    if not entry_data:
        return result
    all_items = entry_data.get(CONF_DIRECTOR_ALL_ITEMS) or []
    for item in all_items:
        if item.get("proxy") != "dynalite_trigger" or not item.get("id"):
            continue
        item_id = item["id"]
        props = await director_get_item_properties(hass, entry, item_id)
        if not props or not isinstance(props, list):
            continue
        area_val: int | None = None
        channel_val: int = 0
        for prop in props:
            if not isinstance(prop, dict):
                continue
            name = prop.get("name")
            val = prop.get("value")
            if name == "Area" and val is not None:
                try:
                    area_val = int(val) if not isinstance(val, int) else val
                except (TypeError, ValueError):
                    pass
            if name == "Channel" and val is not None:
                try:
                    channel_val = int(val) if not isinstance(val, int) else val
                except (TypeError, ValueError):
                    pass
        if area_val is not None:
            key = (area_val, channel_val)
            result[key] = item_id
            name = item.get("name", "")
            _LOGGER.info(
                "Dynalite trigger captured: item_id=%s (C4 Director ID, same as in JSON export) name='%s' area=%s channel=%s",
                item_id,
                name,
                area_val,
                channel_val,
            )
    return result


async def setup_dynalite_listener(
    hass: HomeAssistant, entry: ConfigEntry, entry_data: dict[str, Any]
) -> None:
    """Load Dynalite options, build event map, register callback, and start TCP listener.
    Call only when CONF_DYNALITE_ENABLED is True. Mutates entry_data.
    """
    entry_data[CONF_DYNALITE_PARSE_LAYOUT] = entry.options.get(
        CONF_DYNALITE_PARSE_LAYOUT, DEFAULT_DYNALITE_PARSE_LAYOUT
    )
    entry_data[CONF_DYNALITE_HOST] = (entry.options.get(CONF_DYNALITE_HOST) or "").strip()
    entry_data[CONF_DYNALITE_PORT] = entry.options.get(
        CONF_DYNALITE_PORT, DEFAULT_DYNALITE_PORT
    )
    entry_data["dynalite_event_map"] = await build_dynalite_event_map(hass, entry)
    event_map = entry_data["dynalite_event_map"]
    # Human-readable summary: full data for all triggers (same as in Control4 export JSON)
    all_items = entry_data.get(CONF_DIRECTOR_ALL_ITEMS) or []
    id_to_name = {item["id"]: item.get("name", "") for item in all_items if item.get("id")}
    id_to_room = {item["id"]: item.get("roomName", "") for item in all_items if item.get("id")}
    map_entries = sorted(event_map.items(), key=lambda x: (x[0][0], x[0][1]))
    _LOGGER.info(
        "Dynalite triggers: %s sensors (same id/name/area/channel as in Download JSON export). Full data:",
        len(event_map),
    )
    for (area, ch), iid in map_entries:
        _LOGGER.info(
            "  item_id=%s name='%s' area=%s channel=%s room='%s'",
            iid,
            id_to_name.get(iid, ""),
            area,
            ch,
            id_to_room.get(iid, ""),
        )
    entry_data["dynalite_entities"] = {}
    entry_data["_dynalite_logged_no_mapping"] = set()
    # Collect examples of (area, channel) received from TCP for one-time summary
    entry_data["_dynalite_received_keys"] = set()
    entry_data["_dynalite_received_keys_logged"] = False

    def _on_dynalite_event(area: int, channel: int, value: int) -> None:
        _LOGGER.debug("Dynalite event received: area=%s channel=%s value=%s", area, channel, value)
        ed = (hass.data.get(DOMAIN) or {}).get(entry.entry_id)
        if not ed:
            _LOGGER.debug("Dynalite event: no entry_data for entry_id=%s", entry.entry_id)
            return
        # Log once: examples of (area, channel) keys we receive from TCP
        received = ed.get("_dynalite_received_keys")
        if received is not None and not ed.get("_dynalite_received_keys_logged"):
            received.add((area, channel))
            if len(received) >= 5:
                ed["_dynalite_received_keys_logged"] = True
                examples = sorted(received, key=lambda x: (x[0], x[1]))
                _LOGGER.info(
                    "Dynalite TCP listener: examples of (area, channel) received from gateway: %s",
                    examples,
                )
        event_map = ed.get("dynalite_event_map") or {}
        item_id = event_map.get((area, channel)) or event_map.get((area, 0))
        if item_id is None:
            key = (area, channel)
            logged = ed.get("_dynalite_logged_no_mapping")
            if logged is not None and key not in logged:
                logged.add(key)
                _LOGGER.info(
                    "Dynalite event has no trigger: area=%s channel=%s (configured triggers use areas %s; press a button bound to a dynalite_trigger in Composer)",
                    area,
                    channel,
                    sorted({k[0] for k in event_map.keys()}),
                )
            else:
                _LOGGER.debug(
                    "Dynalite event: no mapping for area=%s channel=%s",
                    area,
                    channel,
                )
            return
        entities = ed.get("dynalite_entities") or {}
        entity = entities.get(item_id)
        if entity is None:
            _LOGGER.debug(
                "Dynalite event: entity not yet registered for item_id=%s (area=%s channel=%s)",
                item_id,
                area,
                channel,
            )
            return
        if hasattr(entity, "set_triggered"):
            _LOGGER.info(
                "Dynalite event matched sensor: item_id=%s area=%s channel=%s name='%s'",
                item_id,
                area,
                channel,
                getattr(entity, "name", "") or "",
            )
            _LOGGER.debug("Dynalite trigger firing for item_id=%s", item_id)
            entity.set_triggered()
        else:
            _LOGGER.debug("Dynalite event: entity %s has no set_triggered", item_id)

    register_dynalite_callback(hass, entry.entry_id, _on_dynalite_event)
    config = {
        CONF_DYNALITE_ENABLED: True,
        CONF_DYNALITE_PARSE_LAYOUT: entry_data.get(
            CONF_DYNALITE_PARSE_LAYOUT, DEFAULT_DYNALITE_PARSE_LAYOUT
        ),
        CONF_DYNALITE_HOST: entry_data[CONF_DYNALITE_HOST],
        CONF_DYNALITE_PORT: entry_data[CONF_DYNALITE_PORT],
    }
    start_dynalite_listener(hass, entry, config)


# 8-byte ACK/heartbeat from gateway (ASCII "lCooMasR")
DYNALITE_ACK = bytes([0x6C, 0x43, 0x6F, 0x6F, 0x4D, 0x61, 0x73, 0x52])
FRAME_LEN = 8
DYNET_CMD = 0x1C


def parse_frame(
    data: bytes,
    layout: str = DEFAULT_DYNALITE_PARSE_LAYOUT,
) -> tuple[int, int, int] | None:
    """Parse 8-byte DyNet-style frame. Returns (area, channel, value) or None if skip.

    layout "bytes_2_3": area=data[2], channel=data[3] (original).
    layout "dynet": area=data[1], channel=data[3] (DyNet standard; byte 3 is opcode).
    """
    if len(data) != FRAME_LEN:
        _LOGGER.debug(
            "Dynalite frame skip: length %s (expected %s) raw=%s",
            len(data),
            FRAME_LEN,
            data.hex() if data else "(empty)",
        )
        return None
    if data == DYNALITE_ACK:
        _LOGGER.debug("Dynalite frame skip: ACK/heartbeat")
        return None
    if data[0] != DYNET_CMD:
        _LOGGER.debug(
            "Dynalite frame skip: cmd 0x%02x (expected 0x1C) raw=%s (enable debug and trigger motion to see if gateway uses this format)",
            data[0],
            data.hex(),
        )
        return None
    if layout == DYNALITE_PARSE_LAYOUT_DYNET:
        area = data[1]
        channel = data[3]  # opcode in DyNet; use as channel for (area, channel) matching
    else:
        area = data[2]
        channel = data[3]
    v1, v2 = data[4], data[5]
    if v1 != 0xFF and v2 != 0xFF:
        value = v1
    else:
        value = 0  # preset/trigger, no numeric value
    _LOGGER.debug(
        "Dynalite frame parsed (layout=%s): area=%s channel=%s value=%s raw=%s",
        layout,
        area,
        channel,
        value,
        data.hex(),
    )
    return (area, channel, value)


def register_dynalite_callback(
    hass: HomeAssistant,
    entry_id: str,
    callback: Callable[[int, int, int], None],
) -> None:
    """Register a callback for Dynalite events (area, channel, value)."""
    hass.data.setdefault(DOMAIN, {})
    entry_data = hass.data[DOMAIN].setdefault(entry_id, {})
    entry_data["dynalite_on_event"] = callback


def _get_callback(hass: HomeAssistant, entry_id: str) -> Callable[[int, int, int], None] | None:
    entry_data = (hass.data.get(DOMAIN) or {}).get(entry_id)
    if not entry_data:
        return None
    return entry_data.get("dynalite_on_event")


def _invoke_callback(hass: HomeAssistant, entry_id: str, area: int, channel: int, value: int) -> None:
    cb = _get_callback(hass, entry_id)
    if cb:
        try:
            cb(area, channel, value)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Dynalite event callback error for area=%s ch=%s", area, channel)


async def _run_tcp_listener(
    hass: HomeAssistant,
    entry_id: str,
    host: str,
    port: int,
    shutdown: asyncio.Event,
    parse_layout: str = DEFAULT_DYNALITE_PARSE_LAYOUT,
) -> None:
    backoff = 1.0
    max_backoff = 60.0
    while not shutdown.is_set():
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=10.0,
            )
        except asyncio.CancelledError:
            break
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Dynalite TCP connect to %s:%s failed: %s; retry in %.0fs",
                host,
                port,
                err,
                backoff,
            )
            try:
                await asyncio.wait_for(shutdown.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, max_backoff)
            continue
        backoff = 1.0
        _LOGGER.info("Dynalite TCP connected to %s:%s", host, port)
        buf = b""
        try:
            while not shutdown.is_set():
                try:
                    data = await asyncio.wait_for(reader.read(4096), timeout=30.0)
                except asyncio.TimeoutError:
                    continue
                if not data:
                    break
                buf += data
                _LOGGER.debug("Dynalite TCP received %s bytes, buf len now %s", len(data), len(buf))
                while len(buf) >= FRAME_LEN:
                    frame = buf[:FRAME_LEN]
                    buf = buf[FRAME_LEN:]
                    parsed = parse_frame(frame, parse_layout)
                    if parsed:
                        area, channel, value = parsed
                        _LOGGER.debug("Dynalite TCP dispatching area=%s channel=%s value=%s", area, channel, value)
                        hass.async_create_task(
                            _invoke_callback_async(hass, entry_id, area, channel, value)
                        )
        except asyncio.CancelledError:
            break
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Dynalite TCP read error: %s", err)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass


async def _invoke_callback_async(
    hass: HomeAssistant, entry_id: str, area: int, channel: int, value: int
) -> None:
    """Invoke the registered callback on the event loop."""
    _LOGGER.debug("Dynalite invoking callback entry_id=%s area=%s channel=%s value=%s", entry_id, area, channel, value)
    cb = _get_callback(hass, entry_id)
    if cb:
        try:
            if asyncio.iscoroutinefunction(cb):
                await cb(area, channel, value)
            else:
                cb(area, channel, value)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Dynalite event callback error for area=%s ch=%s", area, channel)
    else:
        _LOGGER.debug("Dynalite no callback registered for entry_id=%s", entry_id)


def start_dynalite_listener(hass: HomeAssistant, entry: ConfigEntry, config: dict[str, Any]) -> None:
    """Start the Dynalite TCP event listener."""
    entry_id = entry.entry_id
    if not config.get(CONF_DYNALITE_ENABLED):
        return
    entry_data = hass.data.setdefault(DOMAIN, {}).setdefault(entry_id, {})

    stop_dynalite_listener(hass, entry_id)

    host = (config.get(CONF_DYNALITE_HOST) or "").strip()
    port = config.get(CONF_DYNALITE_PORT, DEFAULT_DYNALITE_PORT)
    if not host:
        _LOGGER.warning("Dynalite listener enabled but no host configured")
        return
    shutdown = asyncio.Event()
    entry_data["dynalite_shutdown"] = shutdown
    parse_layout = config.get(
        CONF_DYNALITE_PARSE_LAYOUT, DEFAULT_DYNALITE_PARSE_LAYOUT
    )
    task = asyncio.create_task(
        _run_tcp_listener(hass, entry_id, host, port, shutdown, parse_layout)
    )
    entry_data["dynalite_task"] = task
    _LOGGER.info(
        "Dynalite TCP listener started for %s:%s (parse layout=%s)",
        host,
        port,
        parse_layout,
    )


def stop_dynalite_listener(hass: HomeAssistant, entry_id: str) -> None:
    """Stop the Dynalite TCP listener."""
    entry_data = (hass.data.get(DOMAIN) or {}).get(entry_id)
    if not entry_data:
        return
    task = entry_data.pop("dynalite_task", None)
    if task is not None and not task.done():
        task.cancel()
    shutdown = entry_data.pop("dynalite_shutdown", None)
    if shutdown is not None:
        shutdown.set()
    _LOGGER.debug("Dynalite listener stopped for entry %s", entry_id)
