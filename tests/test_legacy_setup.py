"""Exercise the actual patched setup function with simulated HA/Director services."""

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from xml.parsers.expat import ExpatError, ParserCreate

source = (
    Path(__file__)
    .resolve()
    .parents[1]
    .joinpath("custom_components/control4/__init__.py")
    .read_text(encoding="utf-8")
)
# Compile the real setup function without importing the HA runtime.
tree = ast.parse(source)
setup = next(
    n
    for n in tree.body
    if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry"
)
setup.returns = None
for arg in setup.args.args:
    arg.annotation = None
code = compile(
    ast.fix_missing_locations(ast.Module(body=[setup], type_ignores=[])),
    "patched_setup",
    "exec",
)


class NetworkError(Exception):
    pass


class NotReady(Exception):
    pass


class AuthError(Exception):
    pass


async def run_case(response=None, failure=None):
    director = SimpleNamespace(
        get_all_item_info=AsyncMock(return_value=[{"id": 42, "type": "sensor"}]),
        get_ui_configuration=AsyncMock(return_value=response, side_effect=failure),
    )
    account = SimpleNamespace(
        get_account_controllers=AsyncMock(return_value={"href": "/controller"}),
        get_controller_os_version=AsyncMock(return_value="2.10.6.558226"),
    )
    state = {"CONF_DIRECTOR": director, "CONF_ACCOUNT": account}
    hass = SimpleNamespace(
        data={"control4": {"entry": state}},
        config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock()),
    )
    entry = SimpleNamespace(
        entry_id="entry",
        data={"CONF_CONTROLLER_UNIQUE_ID": "control4_ea5_test"},
        options={},
        add_update_listener=Mock(),
    )
    platforms = [
        "light",
        "alarm_control_panel",
        "binary_sensor",
        "media_player",
        "sensor",
    ]
    logger = Mock()
    env = {
        n.id: n.id
        for n in ast.walk(setup)
        if isinstance(n, ast.Name) and n.id.startswith(("CONF_", "DEFAULT_"))
    }
    env.update(
        DOMAIN="control4",
        refresh_tokens=AsyncMock(),
        update_listener=Mock(),
        PLATFORMS=platforms,
        ExpatError=ExpatError,
        _LOGGER=logger,
        asyncio=asyncio,
        client_exceptions=SimpleNamespace(ClientError=NetworkError),
        ConfigEntryNotReady=NotReady,
        dr=SimpleNamespace(
            async_get=Mock(return_value=SimpleNamespace(async_get_or_create=Mock())),
            CONNECTION_NETWORK_MAC="mac",
        ),
    )
    exec(code, env)
    try:
        result = await env["async_setup_entry"](hass, entry)
    except BaseException:
        hass.config_entries.async_forward_entry_setups.assert_not_awaited()
        raise
    assert result is True
    assert state["CONF_DIRECTOR_ALL_ITEMS"] == [{"id": 42, "type": "sensor"}]
    assert "CONF_ALARM_ARM_STATES" in state
    hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
        entry, platforms
    )
    if failure:
        assert state["CONF_UI_CONFIGURATION"] == {"experiences": []}
        logger.warning.assert_called_once()
    else:
        assert state["CONF_UI_CONFIGURATION"] is response
        logger.warning.assert_not_called()


async def main():
    await run_case(response={"experiences": [{"room_id": 1, "type": "listen"}]})
    print("PASS: valid UI configuration preserved and platforms initialized")
    try:
        ParserCreate().Parse("<html><body><hr></body></html>", True)
    except ExpatError as error:
        await run_case(failure=error)
    else:
        raise AssertionError("Malformed fixture must trigger ExpatError")
    print(
        "PASS: actual malformed-XML exception no longer prevents sensor platform setup"
    )
    for error in [
        AuthError("invalid token"),
        NetworkError("offline"),
        asyncio.CancelledError(),
        ValueError("unrelated bug"),
    ]:
        try:
            await run_case(failure=error)
        except BaseException as caught:
            assert caught is error
        else:
            raise AssertionError("Unrelated error was swallowed")
    print(
        "PASS: authentication, network, cancellation and unrelated errors still propagate"
    )


if __name__ == "__main__":
    asyncio.run(main())
