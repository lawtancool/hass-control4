"""Exercise alarm-zone behavior using lightweight Home Assistant doubles."""

import ast
import asyncio
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, AsyncMock

source = (
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("custom_components/control4/alarm_zone.py")
    .read_text(encoding="utf-8")
)
# Compile the real integration definitions without importing the HA runtime.
tree = ast.parse(source)
nodes = [
    n
    for n in tree.body
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
]


class UpdateFailed(Exception):
    pass


class Coordinator:
    def __init__(
        self,
        hass=None,
        logger=None,
        *,
        name="",
        update_method=None,
        update_interval=None
    ):
        self.data = {}
        self.last_update_success = True
        self.update_method = update_method

    async def async_refresh(self):
        try:
            self.data = await self.update_method()
            self.last_update_success = True
        except UpdateFailed:
            self.last_update_success = False

    def async_set_updated_data(self, rows):
        self.data = rows
        self.last_update_success = True

    def async_update_listeners(self):
        pass

    def async_set_update_error(self, error):
        self.last_update_success = False


class CoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    async def async_added_to_hass(self):
        pass

    async def async_will_remove_from_hass(self):
        pass


class BinarySensorEntity:
    pass


env = dict(
    CoordinatorEntity=CoordinatorEntity,
    BinarySensorEntity=BinarySensorEntity,
    DataUpdateCoordinator=Coordinator,
    UpdateFailed=UpdateFailed,
    BinarySensorDeviceClass=SimpleNamespace(MOTION="motion"),
    DOMAIN="control4",
    CONTROL4_ENTITY_TYPE=7,
    CONF_CONTROLLER_UNIQUE_ID="controller",
    CONF_DIRECTOR="director",
    CONF_DIRECTOR_ALL_ITEMS="items",
    CONF_WEBSOCKET="websocket",
    _LOGGER=Mock(),
    timedelta=timedelta,
)
exec(
    compile(
        ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])),
        "alarm_zone.py",
        "exec",
    ),
    env,
)
zone_rows, zone_open, zone_event = (
    env[x] for x in ("zone_rows", "zone_open", "zone_event")
)
row = {"id": 31, "name": "Example motion sensor", "type": 0, "open": False}
setup = {"panel_setup": {"all_zones": {"zone_info": [row, {"name": "bad"}]}}}
assert zone_rows(setup) == {31: row}
assert zone_rows({"panel_setup": {"all_zones": {"zone_info": row}}}) == {31: row}
assert zone_rows({}) == {}
assert zone_rows({"panel_setup": {"all_zones": {"zone_info": None}}}) == {}
assert zone_open({"open": True}) is True
assert zone_open(row) is False
assert zone_open({}) is None and zone_open({"open": "false"}) is None
message = {"evtName": "OnDataToUI", "data": {"zone_state": {"id": 31, "is_open": True}}}
copy = deepcopy(message)
assert zone_event(message, 31) is True and message == copy
assert zone_event(message, 30) is None
assert (
    zone_event(
        {
            "evtName": "OnDataToUI",
            "data": {"zone_state": {"id": "31", "is_open": False}},
        },
        31,
    )
    is False
)
assert (
    zone_event({"evtName": "OnDataToUI", "data": {"zone_state": {"id": 31}}}, 31)
    is None
)
print("PASS: zone parsing, unknown-state handling and event isolation")


async def main():
    c = Coordinator()
    c.data = {31: deepcopy(row), 32: {"id": 32, "open": False}}
    ws = SimpleNamespace(add_item_callback=Mock(), remove_item_callback=Mock())
    data = {"controller": "test_controller", "websocket": ws}
    entity = env["Control4AlarmZone"](c, data, {"id": 304, "parentId": 303}, 31, row)
    entity.hass = SimpleNamespace(
        async_add_executor_job=AsyncMock(side_effect=lambda f, *args: f(*args))
    )
    assert entity.is_on is False and entity.available
    assert not entity._attr_entity_registry_enabled_default
    await entity.async_added_to_hass()
    assert {a.args[0] for a in ws.add_item_callback.call_args_list} == {303, 304}
    await entity._zone_callback(304, message)
    assert entity.is_on is True and c.data[32]["open"] is False and message == copy
    await entity._zone_callback(
        304,
        {"evtName": "OnDataToUI", "data": {"zone_state": {"id": 32, "is_open": False}}},
    )
    assert entity.is_on is True
    await entity._zone_callback(304, False)
    assert not entity.available
    # A fresh event for one zone must not restore another zone's stale state.
    await entity._zone_callback(304, message)
    assert entity.available and entity.is_on is True and 32 not in c.data
    c.async_set_updated_data = Mock(wraps=c.async_set_updated_data)
    c.async_update_listeners = Mock()
    await entity._zone_callback(304, message)
    c.async_set_updated_data.assert_not_called()
    c.async_update_listeners.assert_called_once()
    c.update_method = AsyncMock(return_value={31: deepcopy(row)})
    await c.async_refresh()
    assert entity.available and entity.is_on is False
    c.data = {}
    assert not entity.available and entity.is_on is None
    await entity.async_will_remove_from_hass()
    assert ws.remove_item_callback.call_count == 2
    print(
        "PASS: live motion, unrelated-zone isolation, disconnect/recovery and callback cleanup"
    )
    panel = {"id": 304, "parentId": 303, "type": 7, "proxy": "securitypanel"}
    director = SimpleNamespace(get_item_setup=AsyncMock(return_value=setup))
    data.update(director=director, items=[panel, {**panel, "id": 303, "type": 6}])
    hass = SimpleNamespace(data={"control4": {"entry": data}})
    added = Mock()
    await env["async_setup_alarm_zones"](hass, SimpleNamespace(entry_id="entry"), added)
    assert len(added.call_args.args[0]) == 1
    assert (
        added.call_args.args[0][0]._attr_unique_id
        == "test_controller_panel_304_zone_31"
    )
    director.get_item_setup.assert_awaited_once_with(304)
    director.get_item_setup.side_effect = ValueError("bad response")
    added = Mock()
    await env["async_setup_alarm_zones"](hass, SimpleNamespace(entry_id="entry"), added)
    added.assert_called_once_with([])
    print(
        "PASS: panel discovery, stable IDs, default-disabled extras and optional API failure"
    )


if __name__ == "__main__":
    asyncio.run(main())
